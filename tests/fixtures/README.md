# wp-media-sync 测试夹具

- `sample-input.json.tpl`：测试 JSON URL 回写、同 URL 去重、常见附件 ID 字段回写、外链视频跳过。
- `sample-input.html.tpl`：测试 HTML 图片回写、`iframe` 内 URL 跳过、外链视频跳过。
- `wp-media-sync-test.png.base64`：1x1 PNG 测试图片；运行测试时解码到 `tests/runtime/source/` 并通过本地 HTTP 服务模拟远程媒体。
