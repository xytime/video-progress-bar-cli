// 隔离基准专用 Vision worker；生产不调用、不自动编译或选择此后端。
// 依赖：benchmark_caption_scan.py → 本 worker → Foundation / Vision。
// 完整 BMP、accurate、简繁英、关闭语言纠正；不裁切、不降采样。
// 原生调用与逐帧 autoreleasepool 去除 JXA 桥接及临时对象积累；性能须实测。
// Modification History: 1.0.0 | 2026-10-31 | Codex | 独立实验后端及分阶段计时，保留完整识别。
#import <Foundation/Foundation.h>
#import <Vision/Vision.h>
#include <time.h>

static double now(void) {
    struct timespec value;
    clock_gettime(CLOCK_MONOTONIC, &value);
    return value.tv_sec + value.tv_nsec / 1e9;
}

static VNRecognizeTextRequest *configuredRequest(void) {
    VNRecognizeTextRequest *request = [[VNRecognizeTextRequest alloc] init];
    request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
    request.recognitionLanguages = @[@"zh-Hans", @"zh-Hant", @"en-US"];
    request.usesLanguageCorrection = NO;
    // 与原 JXA 同为该 OS 默认 revision；显式记录，OS 升级后须重新比对。
    request.revision = VNRecognizeTextRequest.defaultRevision;
    return request;
}

static NSDictionary *recognize(NSString *path, NSNumber *identifier) {
    NSMutableDictionary *measured = [NSMutableDictionary dictionary];
    double started = now();
    NSData *image = [NSData dataWithContentsOfFile:path];
    if (!image.length) return nil;
    measured[@"read_seconds"] = @(now() - started);
    started = now();
    VNRecognizeTextRequest *request = configuredRequest();
    VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithData:image options:@{}];
    measured[@"setup_seconds"] = @(now() - started);
    started = now();
    if (![handler performRequests:@[request] error:nil]) return nil;
    measured[@"recognize_seconds"] = @(now() - started);
    started = now();
    // 失败和成功空帧严格区分；缺少候选时不能静默丢弃该 observation。
    if (!request.results) return nil;
    NSMutableArray *rows = [NSMutableArray array];
    for (VNRecognizedTextObservation *observation in request.results) {
        VNRecognizedText *candidate = [observation topCandidates:1].firstObject;
        if (!candidate) return nil;
        CGRect box = observation.boundingBox;
        [rows addObject:@{@"text": candidate.string, @"confidence": @((double)candidate.confidence),
            @"box": @[@(box.origin.x), @(1 - box.origin.y - box.size.height),
                       @(box.origin.x + box.size.width), @(1 - box.origin.y)]}];
    }
    measured[@"result_seconds"] = @(now() - started);
    return @{@"id": identifier, @"rows": rows, @"worker_metrics": measured,
             @"vision_revision": @(request.revision), @"worker_contract": @"vision-native-bmp-experiment-v1"};
}

int main(void) {
    char *line = NULL;
    size_t capacity = 0;
    ssize_t length;
    long long lastID = 0;
    while ((length = getline(&line, &capacity, stdin)) >= 0) {
        @autoreleasepool {
            id identifier = NSNull.null;
            NSDictionary *result = nil;
            @try {
                id message = length <= 65536 ? [NSJSONSerialization JSONObjectWithData:
                    [NSData dataWithBytes:line length:length] options:0 error:nil] : nil;
                if ([message isKindOfClass:NSDictionary.class]) {
                    id command = message[@"command"];
                    if ([command isEqual:@"STOP"]) { free(line); return 0; }
                    if ([command isEqual:@"INFO"]) {
                        VNRecognizeTextRequest *request = configuredRequest();
                        result = @{@"worker_contract": @"vision-native-bmp-experiment-v1",
                            @"vision_revision": @(request.revision), @"recognition_level": @"accurate",
                            @"recognition_languages": request.recognitionLanguages,
                            @"uses_language_correction": @(request.usesLanguageCorrection),
                            @"per_frame_autoreleasepool": @YES, @"ocr_performed": @NO};
                    } else {
                        id number = message[@"id"], path = message[@"path"];
                        if (!command && [number isKindOfClass:NSNumber.class]
                            && CFGetTypeID((__bridge CFTypeRef)number) != CFBooleanGetTypeID()
                            && !CFNumberIsFloatType((__bridge CFNumberRef)number)
                            && [number longLongValue] > lastID && [number longLongValue] <= 9007199254740991LL
                            && [path isKindOfClass:NSString.class] && [path hasPrefix:@"/"]) {
                            identifier = number;
                            lastID = [number longLongValue];
                            result = recognize(path, number);
                        }
                    }
                }
            } @catch (NSException *exception) {
                result = nil;
            }
            if (!result) result = @{@"id": identifier, @"error": @"VISION_FAILED"};
            NSData *encoded = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingSortedKeys error:nil];
            if (!encoded || fwrite(encoded.bytes, 1, encoded.length, stdout) != encoded.length
                || fputc('\n', stdout) == EOF || fflush(stdout) != 0) {
                free(line); return 2;
            }
        }
    }
    free(line);
    return ferror(stdin) ? 2 : 0;
}
