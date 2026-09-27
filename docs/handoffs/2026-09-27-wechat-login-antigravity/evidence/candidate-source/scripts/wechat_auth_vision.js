/* macOS 视频号授权离线识别适配器，无网络、无模型调用。
 * 依赖：wechat_uploader -> wechat_desktop_auth -> 本文件 -> macOS 原生接口。
 * Modification History
 * | Version | Date | Author | Description |
 * | --- | --- | --- | --- |
 * | 1.0.0 | 2026-09-26 | Codex | 仅可见微信小型候选窗口与 Vision 离线 OCR。 |
 */
ObjC.import('Foundation');
ObjC.import('AppKit');
ObjC.import('CoreGraphics');
ObjC.import('Vision');
function authWindows() {
        var all = ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo(1, 0)));
        return all.filter(function(w) {
            var b = w.kCGWindowBounds, title = w.kCGWindowName || '';
            if (!w.kCGWindowIsOnscreen || w.kCGWindowLayer !== 0 || !b ||
                b.Width < 200 || b.Width > 700 || b.Height < 120 || b.Height > 900) return false;
            if (['WeChat', '微信'].indexOf(w.kCGWindowOwnerName) < 0) return false;
            var app = $.NSRunningApplication.runningApplicationWithProcessIdentifier(w.kCGWindowOwnerPID);
            if (!app || ObjC.unwrap(app.bundleIdentifier) !== 'com.tencent.xinWeChat') return false;
            // 主聊天窗口和设置页不进入截图候选；不依赖单纯绿色按钮。
            return title === '' || ['视频号创作平台', '微信登录', '授权登录'].indexOf(title) >= 0;
        }).map(function(w) {
            return {id: w.kCGWindowNumber, pid: w.kCGWindowOwnerPID, bounds: w.kCGWindowBounds};
        });
}
function run(args) {
    if (args[0] === 'windows') return JSON.stringify(authWindows());
    if (args[0] === 'click' && args.length === 2) {
        var target = JSON.parse(args[1]), b = target.window.bounds;
        var front = $.NSWorkspace.sharedWorkspace.frontmostApplication;
        if (!front || ObjC.unwrap(front.bundleIdentifier) !== 'com.tencent.xinWeChat') return 'false';
        var present = authWindows().some(function(w) { return JSON.stringify(w) === JSON.stringify(target.window); });
        if (!present || !Number.isFinite(target.x) || !Number.isFinite(target.y) ||
            target.x < b.X || target.x >= b.X + b.Width || target.y < b.Y || target.y >= b.Y + b.Height ||
            !Number.isFinite(target.expiresAt) || Date.now() >= target.expiresAt) return 'false';
        var point = $.CGPointMake(target.x, target.y);
        // Qt 自绘按钮可能拒绝 AXPress；仅已验证的授权窗口使用原生鼠标事件。
        $.CGEventPost(0, $.CGEventCreateMouseEvent(null, 1, point, 0));
        $.CGEventPost(0, $.CGEventCreateMouseEvent(null, 2, point, 0));
        return 'true';
    }
    if (args[0] !== 'ocr' || args.length !== 2) throw Error('INVALID_ARGUMENTS');
    var req = $.VNRecognizeTextRequest.alloc.init;
    req.recognitionLevel = 0;
    req.recognitionLanguages = $(['zh-Hans', 'en-US']);
    req.usesLanguageCorrection = false;
    var handler = $.VNImageRequestHandler.alloc.initWithURLOptions($.NSURL.fileURLWithPath(args[1]), $({}));
    var error = Ref();
    if (!handler.performRequestsError($([req]), error)) throw Error('OCR_FAILED');
    var out = [];
    for (var i = 0; i < req.results.count; i++) {
        var ob = req.results.objectAtIndex(i), top = ob.topCandidates(1).objectAtIndex(0), b = ob.boundingBox;
        out.push({text: ObjC.unwrap(top.string), confidence: top.confidence,
                  box: [b.origin.x, b.origin.y, b.size.width, b.size.height]});
    }
    return JSON.stringify(out);
}
