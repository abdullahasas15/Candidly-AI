// swift-tools-version:5.9
// R3.5: Apple on-device STT helper (SpeechAnalyzer on macOS 26+, SFSpeechRecognizer fallback).
// Language mode v5 keeps concurrency checking pragmatic for a small CLI while running
// on the modern toolchain.
import PackageDescription

let package = Package(
    name: "apple_stt",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "apple_stt",
            path: "Sources/apple_stt"
        )
    ]
)
