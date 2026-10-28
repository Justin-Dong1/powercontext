# Runtime validation

Validation date: 2026-10-28 (Asia/Shanghai)

## Static contract

```text
STEPFUN_SUBMISSION_VALIDATION_PASS
  PASS INT8 q8
  PASS WebGPU 优先
  PASS WASM 降级
  PASS seekdb-js
  PASS 384 维索引
  PASS 数据库原生混合检索
  PASS RRF 排序
```

## Unit and production build

```text
tests 2; pass 2; fail 0
vite v8.3.5
29 modules transformed
build completed
```

## Real seekdb-js server-mode smoke test

Environment: official `oceanbase/seekdb:latest` image, local-only port mapping, database `edge_rag`; application connected through seekdb-js 1.4.0.

```json
{
  "status": "STEPFUN_SEEKDB_SMOKE_PASS",
  "upsert": { "written": 2, "total": 2 },
  "resultIds": ["webgpu"],
  "searchMs": 77.0213
}
```

The smoke script supplied caller-generated 384-dimensional vectors, persisted two documents, then invoked the same `collection.hybridSearch()` + RRF path used by the Web application. This verifies real seekdb storage and database-side hybrid retrieval; it is not a browser/WebGPU benchmark.
