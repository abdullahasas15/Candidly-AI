// R3.5 — apple_stt: on-device speech-to-text helper for Candidly.
//
// Protocol (R3.5 Part 1):
//   stdin  : raw 16 kHz mono PCM16 (little-endian) audio, streamed continuously.
//   stdout : one JSON object per line:
//     {"type":"ready","provider":...,"locale":...,"control_port":N}
//     {"type":"partial","text":...,"start":s,"end":s,"seq":n}
//     {"type":"final","text":...,"start":s,"end":s,"seq":n}
//     {"type":"model_status","installed":true|false,"needs_download":bool}
//     {"type":"model_download","progress":0.0...1.0}
//     {"type":"error","message":...,"code":...}
//   control: localhost TCP socket (port announced in `ready`). Commands (LF-terminated):
//     FLUSH  -> finalize everything transcribed so far (emit final)
//     PING   -> reply {"type":"pong"}
//     EXIT   -> clean shutdown
//
// Modes:
//   speechanalyzer (macOS 26+): SpeechAnalyzer + SpeechTranscriber, volatile results.
//   sfspeech       (macOS 13+): on-device SFSpeechRecognizer, request restart without word loss.
//   --check        : print readiness JSON and exit 0.

import Foundation
import AVFoundation
import Speech
import Network

// ---------------------------------------------------------------------------
// CLI arguments
// ---------------------------------------------------------------------------

struct CLIArgs {
    var mode: String = "speechanalyzer"
    var locale: String = "en-US"
    var checkOnly: Bool = false
    var contextFile: String? = nil
}

func parseArgs() -> CLIArgs {
    var args = CLIArgs()
    var it = CommandLine.arguments.makeIterator()
    _ = it.next()
    while let a = it.next() {
        switch a {
        case "--mode": args.mode = it.next() ?? args.mode
        case "--locale": args.locale = it.next() ?? args.locale
        case "--check": args.checkOnly = true
        case "--context": args.contextFile = it.next()
        default: break
        }
    }
    return args
}

func loadContextTerms(_ path: String?) -> [String] {
    guard let path, !path.isEmpty else { return [] }
    guard let raw = try? String(contentsOfFile: path, encoding: .utf8) else { return [] }
    return raw
        .split(whereSeparator: { $0 == "\n" || $0 == "," })
        .map { $0.trimmingCharacters(in: .whitespaces) }
        .filter { !$0.isEmpty }
        .prefix(100)
        .map { String($0) }
}

// ---------------------------------------------------------------------------
// JSON line output (serialized, flushed)
// ---------------------------------------------------------------------------

let stdoutLock = NSLock()

func emit(_ dict: [String: Any]) {
    guard JSONSerialization.isValidJSONObject(dict),
          let data = try? JSONSerialization.data(withJSONObject: dict),
          let line = String(data: data, encoding: .utf8) else { return }
    stdoutLock.lock()
    FileHandle.standardOutput.write((line + "\n").data(using: .utf8)!)
    stdoutLock.unlock()
}

func emitError(_ message: String, code: String = "runtime") {
    emit(["type": "error", "message": message, "code": code])
}

// Diagnostics to stderr (never corrupts the stdout JSON protocol).
func dlog(_ message: String) {
    let line = "[apple_stt] \(message)\n"
    FileHandle.standardError.write(line.data(using: .utf8)!)
}

// ---------------------------------------------------------------------------
// Control socket (Network.framework) — FLUSH / PING / EXIT commands
// ---------------------------------------------------------------------------

final class ControlServer {
    private var listener: NWListener?
    private var connections: [NWConnection] = []
    private let queue = DispatchQueue(label: "candidly.apple_stt.control")
    var onCommand: ((String) -> Void)?

    func start() -> UInt16? {
        let params = NWParameters.tcp
        params.allowLocalEndpointReuse = true
        guard let listener = try? NWListener(using: params, on: .any) else { return nil }
        self.listener = listener
        let sem = DispatchSemaphore(value: 0)
        var boundPort: UInt16 = 0
        listener.stateUpdateHandler = { state in
            if case .ready = state, let port = listener.port?.rawValue {
                boundPort = port
                sem.signal()
            }
            if case .failed = state { sem.signal() }
        }
        listener.newConnectionHandler = { [weak self] conn in
            self?.connections.append(conn)
            conn.start(queue: self?.queue ?? DispatchQueue.global())
            self?.receive(on: conn)
        }
        listener.start(queue: queue)
        _ = sem.wait(timeout: .now() + 2.0)
        return boundPort == 0 ? nil : boundPort
    }

    private func receive(on conn: NWConnection) {
        conn.receive(minimumIncompleteLength: 1, maximumLength: 4096) { [weak self] data, _, done, err in
            if let data, let text = String(data: data, encoding: .utf8) {
                for cmd in text.split(separator: "\n") {
                    self?.onCommand?(cmd.trimmingCharacters(in: .whitespaces).uppercased())
                }
            }
            if err != nil || done {
                return
            }
            self?.receive(on: conn)
        }
    }

    func sendReply(_ text: String) {
        let payload = (text + "\n").data(using: .utf8)!
        for conn in connections {
            conn.send(content: payload, completion: .contentProcessed { _ in })
        }
    }

    func stop() {
        listener?.cancel()
        for c in connections { c.cancel() }
    }
}

// ---------------------------------------------------------------------------
// Shared stdin pump: reads PCM16/16k/mono chunks and hands them to the engine
// ---------------------------------------------------------------------------

final class StdinPump {
    private let chunkSize = 6400  // 200 ms @ 16 kHz / 16-bit / mono
    private let queue = DispatchQueue(label: "candidly.apple_stt.stdin")
    var onChunk: ((Data) -> Void)?
    var onEOF: (() -> Void)?
    private var stopped = false

    func run() {
        queue.async { [weak self] in
            guard let self else { return }
            let input = FileHandle.standardInput
            while !self.stopped {
                let data = input.readData(ofLength: self.chunkSize)
                if data.isEmpty {
                    self.onEOF?()
                    return
                }
                self.onChunk?(data)
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Engine A — SpeechAnalyzer + SpeechTranscriber (macOS 26+)
// ---------------------------------------------------------------------------

@available(macOS 26.0, *)
final class AnalyzerEngine {
    // R3.5 final architecture (evidence-driven):
    //  ONE SpeechAnalyzer session is created at helper boot (warmed on 1.5s of silence)
    //  and lives for the entire interview. Rebuilt sessions were shown to drop utterance
    //  heads; a single warm session transcribes every word with punctuation, exactly
    //  like Mac dictation. Mid-interview we NEVER force-finalize: the Python side ships
    //  stitched partials at turn commit and appends spontaneous segment finals as they
    //  arrive. finalizeAndFinish runs only at stdin EOF (end of interview).
    private let localeSupported: Locale
    private let contextTerms: [String]
    private let converter: AVAudioConverter
    private let targetFormat: AVAudioFormat
    private let seqLock = NSLock()
    private var segmentSeq: Int = 0
    private var base0: UnsafeRawPointer? = nil
    private var fedFrames = 0

    private let analyzer: SpeechAnalyzer
    private let transcriber: SpeechTranscriber
    private let inputCont: AsyncStream<AnalyzerInput>.Continuation

    init(localeId: String, contextTerms: [String]) async throws {
        let requested = Locale(identifier: localeId)
        let supported = (try? await SpeechTranscriber.supportedLocale(equivalentTo: requested)) ?? requested
        localeSupported = supported
        self.contextTerms = contextTerms

        let transcriber = SpeechTranscriber(
            locale: supported,
            transcriptionOptions: [],
            reportingOptions: [.volatileResults, .fastResults],
            attributeOptions: [.audioTimeRange, .transcriptionConfidence]
        )
        self.transcriber = transcriber
        let analyzer = SpeechAnalyzer(modules: [transcriber])
        self.analyzer = analyzer

        guard let fmt = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [transcriber]) else {
            throw NSError(domain: "apple_stt", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "No compatible audio format"])
        }
        targetFormat = fmt
        let srcFormat = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true)!
        converter = AVAudioConverter(from: srcFormat, to: fmt)!

        if !contextTerms.isEmpty {
            let ctx = AnalysisContext()
            ctx.contextualStrings = [.general: contextTerms]
            try? await analyzer.setContext(ctx)
        }

        let (stream, cont) = AsyncStream<AnalyzerInput>.makeStream(bufferingPolicy: .unbounded)
        inputCont = cont

        // Results pump: volatile => partial, final => final.
        // MUST be actively iterating before start(inputSequence:) — else volatile
        // results are silently dropped (verified empirically).
        let pumpHandshake = DispatchSemaphore(value: 0)
        Task.detached(priority: .userInitiated) { [transcriber] in
            dlog("results pump: starting")
            pumpHandshake.signal()
            do {
                for try await result in transcriber.results {
                    let text = String(result.text.characters).trimmingCharacters(in: .whitespacesAndNewlines)
                    if text.isEmpty { continue }
                    let start = result.range.start.seconds
                    let end = (result.range.start + result.range.duration).seconds
                    if result.isFinal {
                        self.markSeq()
                        emit(["type": "final", "text": text,
                              "start": round(start * 1000) / 1000.0,
                              "end": round(end * 1000) / 1000.0,
                              "seq": self.segmentSeqValue()])
                    } else {
                        emit(["type": "partial", "text": text,
                              "start": round(start * 1000) / 1000.0,
                              "end": round(end * 1000) / 1000.0, "seq": 0])
                    }
                }
            } catch {
                let desc = String(describing: error)
                if !desc.contains("cancel") {
                    emitError("results stream failed: \(desc)", code: "results")
                }
            }
        }
        pumpHandshake.wait()

        try await analyzer.start(inputSequence: stream)
        try await analyzer.prepareToAnalyze(in: fmt)
        emit(["type": "ready", "provider": "apple_speechanalyzer", "locale": supported.identifier])
    }

    private func markSeq() {
        seqLock.lock(); defer { seqLock.unlock() }
        segmentSeq += 1
    }

    private func segmentSeqValue() -> Int {
        seqLock.lock(); defer { seqLock.unlock() }
        return segmentSeq
    }

    func feed(_ data: Data) {
        data.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
            guard let start = raw.baseAddress else { return }
            var offset = 0
            let total = raw.count
            while offset < total {
                let n = min(6400, total - offset)
                let nSamples = n / 2
                guard nSamples > 0 else { return }
                base0 = start.advanced(by: offset)
                guard let inBuf = AVAudioPCMBuffer(pcmFormat: converter.inputFormat,
                                                   frameCapacity: AVAudioFrameCount(nSamples)) else { return }
                inBuf.frameLength = AVAudioFrameCount(nSamples)
                memcpy(UnsafeMutableRawPointer(inBuf.int16ChannelData![0]), base0, nSamples * 2)

                guard let outBuf = AVAudioPCMBuffer(pcmFormat: targetFormat,
                                                    frameCapacity: AVAudioFrameCount(Double(nSamples) * 4.0) + 64) else { return }
                var convError: NSError?
                var pumpBuf: AVAudioPCMBuffer? = inBuf
                let _ = converter.convert(to: outBuf, error: &convError) { _, outStatus in
                    let buf = pumpBuf
                    pumpBuf = nil
                    if let buf {
                        outStatus.pointee = .haveData
                        return buf
                    }
                    outStatus.pointee = .noDataNow
                    return nil
                }
                if let convError {
                    emitError("audio convert failed: \(convError)", code: "convert")
                    return
                }
                if outBuf.frameLength > 0 {
                    inputCont.yield(AnalyzerInput(buffer: outBuf))
                    fedFrames += Int(outBuf.frameLength)
                    if fedFrames % 16000 < 400 {
                        dlog("fed total=\(fedFrames)")
                    }
                }
                offset += n
            }
        }
    }

    // Mid-stream flush (R3.5b): the analyzer's finalize IS the commit-time answer of
    // record. finalize(through: currentFeedTime) sets a finalization boundary at the
    // last fed audio — the pending volatile range is flushed out of the results pump
    // as final(s) and the session stays warm for audio fed afterwards.
    func flush() async {
        guard fedFrames > 0 else {
            dlog("FLUSH: no audio fed yet, nothing to finalize")
            return
        }
        let throughSecs = Double(fedFrames) / max(1.0, targetFormat.sampleRate)
        let t = CMTime(seconds: throughSecs, preferredTimescale: 16000)
        dlog("FLUSH: finalize(through: \(throughSecs)s)")
        try? await analyzer.finalize(through: t)
        dlog("FLUSH: finalize returned")
    }

    func shutdown() async {
        // End of interview: emit the remaining finalized transcript once.
        // Individually finalize(through:) and finalizeAndFinishThroughEndOfInput() can
        // hang without emitting; firing BOTH detached reliably flushes every pending
        // segment final out of the results stream (empirically proven).
        dlog("SHUTDOWN: fed=\(fedFrames)")
        let analyzerRef = self.analyzer
        if fedFrames > 0 {
            let t = CMTime(seconds: Double(fedFrames) / max(1.0, targetFormat.sampleRate),
                           preferredTimescale: 16000)
            Task.detached(priority: .userInitiated) { _ = try? await analyzerRef.finalize(through: t) }
            Task.detached(priority: .userInitiated) { _ = try? await analyzerRef.finalizeAndFinishThroughEndOfInput() }
        } else {
            Task.detached(priority: .userInitiated) { _ = try? await analyzerRef.finalizeAndFinishThroughEndOfInput() }
        }
        dlog("SHUTDOWN: finalize commands fired")
        // Let the finalized results stream out before the process exits.
        try? await Task.sleep(nanoseconds: 2_500_000_000)
        dlog("SHUTDOWN: done")
        inputCont.finish()
    }
}

@available(macOS 26.0, *)
extension AnalyzerEngine {
    // Reserved for future session diagnostics.
}

// ---------------------------------------------------------------------------
// Engine B — SFSpeechRecognizer on-device (macOS 13-25 fallback)
// ---------------------------------------------------------------------------

final class SFSpeechEngine {
    private let recognizer: SFSpeechRecognizer?
    private let localeId: String
    private let contextTerms: [String]
    private let lock = NSLock()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var baseline: String = ""     // finalized text from previous requests
    private var appendedSamples: Int = 0
    private var segmentSeq: Int = 0
    private var authorized = false

    // Restart before the on-device recognition length limit without losing words.
    private let maxRequestSamples = 45 * 16000

    init(localeId: String, contextTerms: [String]) {
        self.localeId = localeId
        self.contextTerms = contextTerms
        recognizer = SFSpeechRecognizer(locale: Locale(identifier: localeId))
    }

    func start() async {
        guard SFSpeechRecognizer.authorizationStatus() == .authorized else {
            emitError("SFSpeechRecognizer not authorized (requires speech-recognition TCC grant; run inside a signed .app wrapper)", code: "not_authorized")
            return
        }
        guard let recognizer, recognizer.isAvailable else {
            emitError("SFSpeechRecognizer unavailable for locale \(localeId)", code: "locale_unavailable")
            return
        }
        authorized = true
        emit(["type": "ready", "provider": "apple_sfspeech", "locale": localeId])
        startNewRequest()
    }

    private func startNewRequest() {
        guard let recognizer else { return }
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        req.requiresOnDeviceRecognition = true
        if #available(macOS 13.0, *), !contextTerms.isEmpty {
            req.contextualStrings = contextTerms
        }
        request = req
        task = recognizer.recognitionTask(with: req) { [weak self] result, error in
            guard let self else { return }
            self.lock.lock(); defer { self.lock.unlock() }
            if let result {
                var text = result.bestTranscription.formattedString
                if !self.baseline.isEmpty, text.hasPrefix(self.baseline) {
                    text = String(text.dropFirst(self.baseline.count))
                }
                text = text.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !text.isEmpty else { return }
                if result.isFinal {
                    self.baseline = (self.baseline + " " + text).trimmingCharacters(in: .whitespaces)
                    self.segmentSeq += 1
                    emit(["type": "final", "text": text, "start": 0.0, "end": 0.0, "seq": self.segmentSeq])
                } else {
                    emit(["type": "partial", "text": text, "start": 0.0, "end": 0.0, "seq": 0])
                }
            }
            if error != nil {
                emitError("recognition error: \(error!.localizedDescription)", code: "recognition")
            }
        }
    }

    func feed(_ data: Data) {
        guard authorized else { return }
        lock.lock(); defer { lock.unlock() }
        let nSamples = data.count / 2
        guard let format = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true),
              let buf = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(nSamples)) else { return }
        buf.frameLength = AVAudioFrameCount(nSamples)
        _ = data.withUnsafeBytes { raw in
            guard let src = raw.baseAddress else { return }
            memcpy(buf.int16ChannelData![0], src, nSamples * 2)
        }
        request?.append(buf)
        appendedSamples += nSamples
        if appendedSamples >= maxRequestSamples {
            request?.endAudio()
            request = nil
            appendedSamples = 0
            startNewRequest()
        }
    }

    func flush() {
        lock.lock(); defer { lock.unlock() }
        // Finish the live request to force finalization; next audio opens a new request.
        request?.endAudio()
        request = nil
        appendedSamples = 0
        startNewRequest()
    }
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

final class EngineBox {
    // Thread-safe box so the control-socket callback can reach the active engine.
    var flushHandler: (() -> Void)?
    var flushAllHandler: (() -> Void)?
    var pingHandler: (() -> Void)?
}

@main
struct Main {
    static func main() async {
        let args = parseArgs()
        let terms = loadContextTerms(args.contextFile)

        if args.checkOnly {
            await runCheck(args: args)
            return
        }

        let box = EngineBox()
        let control = ControlServer()
        control.onCommand = { cmd in
            dlog("control cmd: \(cmd) flushSet=\(box.flushHandler != nil)")
            switch cmd {
            case "FLUSH": box.flushHandler?()
            case "FLUSH_ALL": box.flushAllHandler?()
            case "PING": control.sendReply("{\"type\":\"pong\"}")
            case "EXIT": exit(0)
            default: break
            }
        }
        let port = control.start()
        if port == nil {
            emitError("control socket failed to start", code: "control")
        }

        let pump = StdinPump()
        let eof = DispatchSemaphore(value: 0)

        if args.mode == "speechanalyzer", #available(macOS 26.0, *) {
            do {
                let engine = try await AnalyzerEngine(localeId: args.locale, contextTerms: terms)
                emit(["type": "model_status", "installed": true, "needs_download": false])
                if let port {
                    emit(["type": "meta", "control_port": port, "mode": "speechanalyzer"])
                }
                box.flushHandler = { Task.detached(priority: .userInitiated) { dlog("TASK FIRES (flush)"); await engine.flush() } }
                box.flushAllHandler = { Task.detached(priority: .userInitiated) { dlog("TASK FIRES (flushall)"); await engine.flush() } }
                dlog("engine wired: flushHandler set=\(box.flushHandler != nil)")
                pump.onChunk = { engine.feed($0) }
                pump.onEOF = { Task.detached(priority: .userInitiated) { await engine.shutdown(); eof.signal() } }
            } catch {
                emitError("speechanalyzer init failed: \(error)", code: "init_failed")
                exit(3)
            }
        } else {
            let engine = SFSpeechEngine(localeId: args.locale, contextTerms: terms)
            await engine.start()
            if let port {
                emit(["type": "meta", "control_port": port, "mode": "sfspeech"])
            }
            box.flushHandler = { engine.flush() }
            pump.onChunk = { engine.feed($0) }
            pump.onEOF = { eof.signal() }
        }

        pump.run()
        eof.wait()
        exit(0)
    }

    static func runCheck(args: CLIArgs) async {
        if args.mode == "speechanalyzer" {
            guard #available(macOS 26.0, *) else {
                emit(["type": "check", "provider": "apple_speechanalyzer", "supported": false,
                      "installed": false, "needs_download": false, "detail": "requires macOS 26+"])
                return
            }
            do {
                let requested = Locale(identifier: args.locale)
                let supported = await SpeechTranscriber.supportedLocale(equivalentTo: requested)
                guard let supported else {
                    emit(["type": "check", "provider": "apple_speechanalyzer", "supported": false,
                          "installed": false, "needs_download": false,
                          "detail": "locale \(args.locale) not supported"])
                    return
                }
                let transcriber = SpeechTranscriber(
                    locale: supported,
                    transcriptionOptions: [],
                    reportingOptions: [.volatileResults],
                    attributeOptions: []
                )
                let status = await AssetInventory.status(forModules: [transcriber])
                let installed = (status == .supported || status == .installed)
                let installReq = try? await AssetInventory.assetInstallationRequest(supporting: [transcriber])
                emit(["type": "check", "provider": "apple_speechanalyzer", "supported": true,
                      "installed": installed, "needs_download": installReq != nil,
                      "detail": "status=\(status)"])
            } catch {
                emit(["type": "check", "provider": "apple_speechanalyzer", "supported": true,
                      "installed": false, "needs_download": true, "detail": "\(error)"])
            }
        } else {
            let ok = SFSpeechRecognizer.authorizationStatus() == .authorized
            emit(["type": "check", "provider": "apple_sfspeech",
                  "supported": SFSpeechRecognizer.authorizationStatus() != .denied,
                  "installed": ok, "needs_download": false,
                  "detail": "tcc_status=\(SFSpeechRecognizer.authorizationStatus().rawValue)"])
        }
    }
}
