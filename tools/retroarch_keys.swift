// Inject keyboard events into one exact RetroArch process using CoreGraphics.
// Does not change global keybinds and does not need the app to own focus.
// Usage:
//   swift tools/retroarch_keys.swift hold <pid> <seconds> <keycode> [keycodes...]
//   swift tools/retroarch_keys.swift down <pid> <keycode> [keycodes...]
//   swift tools/retroarch_keys.swift up   <pid> <keycode> [keycodes...]
import Foundation
import CoreGraphics

func fail(_ message: String) -> Never {
    fputs("retroarch_keys: \(message)\n", stderr)
    exit(2)
}
let args = Array(CommandLine.arguments.dropFirst())
guard args.count >= 3 else { fail("missing action, pid or keycodes") }
let action = args[0]
guard ["hold", "down", "up"].contains(action) else { fail("unsupported action") }
guard let pid = Int32(args[1]), pid > 0 else { fail("invalid target PID") }
var offset = 2
var duration = 0.0
if action == "hold" {
    guard args.count >= 4, let seconds = Double(args[2]),
          seconds >= 0, seconds <= 90 else { fail("invalid hold duration") }
    duration = seconds
    offset = 3
}
guard offset < args.count else { fail("no keyboard codes") }
let keys: [CGKeyCode] = args[offset...].map { value in
    guard let n = UInt16(value), n <= 127 else { fail("invalid keycode: \(value)") }
    return CGKeyCode(n)
}

func post(_ down: Bool, _ keys: [CGKeyCode]) {
    for code in keys {
        guard let event = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: down) else {
            fail("cannot create CGEvent; macOS accessibility permission may be missing")
        }
        event.postToPid(pid_t(pid))
    }
}
switch action {
case "down":
    post(true, keys)
case "up":
    post(false, keys.reversed().map { $0 })
case "hold":
    post(true, keys)
    Thread.sleep(forTimeInterval: duration)
    post(false, keys.reversed().map { $0 })
default:
    fail("unreachable action")
}
