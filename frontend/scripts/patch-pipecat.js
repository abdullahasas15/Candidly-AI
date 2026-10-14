/**
 * Ensures Pipecat client and transport safely handle plain object and cloned Headers.
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const frontendDir = path.resolve(__dirname, '..');

const filesToPatch = [
  path.join(frontendDir, 'node_modules', '@pipecat-ai', 'client-js', 'dist', 'index.module.js'),
  path.join(frontendDir, 'node_modules', '@pipecat-ai', 'client-js', 'dist', 'index.js'),
  path.join(frontendDir, 'node_modules', '@pipecat-ai', 'small-webrtc-transport', 'dist', 'index.module.js'),
  path.join(frontendDir, 'node_modules', '@pipecat-ai', 'small-webrtc-transport', 'dist', 'index.js'),
];

filesToPatch.forEach((filePath) => {
  if (!fs.existsSync(filePath)) return;
  let content = fs.readFileSync(filePath, 'utf8');

  // Replace unsafe (cxnOpts.headers ?? new Headers()).entries()
  const unsafe1 = '...Object.fromEntries((cxnOpts.headers ?? new Headers()).entries())';
  const safe1 = '...((cxnOpts.headers && typeof cxnOpts.headers.entries === "function") ? Object.fromEntries(cxnOpts.headers.entries()) : (cxnOpts.headers && typeof cxnOpts.headers === "object") ? cxnOpts.headers : {})';

  // Replace unsafe (this._webrtcRequest.headers ?? new Headers()).entries()
  const unsafe2 = '...Object.fromEntries((this._webrtcRequest.headers ?? new Headers()).entries())';
  const safe2 = '...((this._webrtcRequest.headers && typeof this._webrtcRequest.headers.entries === "function") ? Object.fromEntries(this._webrtcRequest.headers.entries()) : (this._webrtcRequest.headers && typeof this._webrtcRequest.headers === "object") ? this._webrtcRequest.headers : {})';

  let modified = false;
  if (content.includes(unsafe1)) {
    content = content.replace(unsafe1, safe1);
    modified = true;
  }
  if (content.includes(unsafe2)) {
    content = content.replace(unsafe2, safe2);
    modified = true;
  }

  if (modified) {
    fs.writeFileSync(filePath, content, 'utf8');
    console.log(`[patch-pipecat] Successfully patched ${filePath}`);
  }
});
