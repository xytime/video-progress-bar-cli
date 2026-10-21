// 本地逐帧 PNG -> Vision 文本框；不接收命令或远端 URL。
// Modification History: 1.0.0 | 2026-10-21 | Codex | 原位字幕修补的常驻本机识别适配。
ObjC.import('Foundation');
ObjC.import('Vision');
function run() {
    const input = $.NSFileHandle.fileHandleWithStandardInput;
    const output = $.NSFileHandle.fileHandleWithStandardOutput;
    let buffer = '';
    while (true) {
        const chunk = input.availableData;
        if (chunk.length === 0) break;
        buffer += ObjC.unwrap($.NSString.alloc.initWithDataEncoding(chunk, $.NSUTF8StringEncoding));
        let newline;
        while ((newline = buffer.indexOf('\n')) >= 0) {
            const line = buffer.slice(0, newline);
            buffer = buffer.slice(newline + 1);
            let result;
            try {
                const image = $.NSData.alloc.initWithBase64EncodedStringOptions($(line), 0);
                const request = $.VNRecognizeTextRequest.alloc.init;
                request.recognitionLevel = 0;
                request.recognitionLanguages = $(['en-US', 'zh-Hans']);
                request.usesLanguageCorrection = false;
                const handler = $.VNImageRequestHandler.alloc.initWithDataOptions(image, $({}));
                if (!handler.performRequestsError($([request]), Ref())) throw Error('VISION_FAILED');
                const rows = [];
                for (let i = 0; i < request.results.count; i++) {
                    const observation = request.results.objectAtIndex(i);
                    const candidate = observation.topCandidates(1).objectAtIndex(0);
                    const b = observation.boundingBox;
                    rows.push({text: ObjC.unwrap(candidate.string), confidence: candidate.confidence,
                        box: [b.origin.x, 1-b.origin.y-b.size.height,
                              b.origin.x+b.size.width, 1-b.origin.y]});
                }
                result = {rows: rows};
            } catch (error) { result = {error: 'VISION_FAILED'}; }
            output.writeData($(JSON.stringify(result) + '\n').dataUsingEncoding($.NSUTF8StringEncoding));
        }
    }
    return '';
}
