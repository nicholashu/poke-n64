// OCR for actual RetroArch screenshots using macOS Vision (no cloud calls).
// Usage: swift tools/retroarch_ocr.swift path/to/frame.png
import Foundation
import AppKit
import Vision

guard CommandLine.arguments.count == 2 else {
    fputs("Usage: retroarch_ocr.swift <image.png>\n", stderr)
    exit(2)
}
let imagePath = CommandLine.arguments[1]
guard let image = NSImage(contentsOfFile: imagePath) else {
    fputs("Unable to read screenshot: \(imagePath)\n", stderr)
    exit(2)
}
var rect = CGRect(origin: .zero, size: image.size)
guard let cg = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
    fputs("Unable to decode screenshot\n", stderr)
    exit(2)
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false

do {
    try VNImageRequestHandler(cgImage: cg).perform([request])
    for observation in request.results ?? [] {
        if let candidate = observation.topCandidates(1).first {
            print(candidate.string)
        }
    }
} catch {
    fputs("Vision OCR error: \(error)\n", stderr)
    exit(1)
}
