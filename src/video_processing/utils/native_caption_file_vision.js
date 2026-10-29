// 整片原字幕分流文件传输；识别参数与旧版一致。
// Modification History: 1.0.0 | 2026-10-29 | Codex | 无损文件输入与请求编号绑定。
// Modification History: 1.1.0 | 2026-10-29 | Codex | 显式 STOP 避免 JXA 对空 stdin 的退出等待，不改变任何识别参数。
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
            let result, message;
            try {
                message = JSON.parse(line);
                if (message.command === 'STOP') return '';
                const image = $.NSData.dataWithContentsOfFile($(message.path));
                if (!image || image.length === 0) throw Error('VISION_INPUT');
                const request = $.VNRecognizeTextRequest.alloc.init;
                request.recognitionLevel = 0;
                request.recognitionLanguages = $(['zh-Hans', 'zh-Hant', 'en-US']);
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
            result.id = message ? message.id : null;
            output.writeData($(JSON.stringify(result) + '\n').dataUsingEncoding($.NSUTF8StringEncoding));
        }
    }
    return '';
}
