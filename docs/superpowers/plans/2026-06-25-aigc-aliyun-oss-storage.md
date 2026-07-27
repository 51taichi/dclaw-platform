# AIGC Aliyun OSS Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store new AIGC Studio generated assets in Aliyun OSS when admin configuration enables it.

**Architecture:** Add a focused backend object storage module and admin router, then integrate it into AIGC Studio's generated-asset save and read paths. The frontend adds one admin settings page for Aliyun OSS configuration.

**Tech Stack:** FastAPI, httpx, HMAC-SHA1 OSS V1 signing, Pydantic, Vitest, React, Ant Design.

---

### Task 1: Backend Object Storage Module

**Files:**
- Create: `src/qwenpaw/app/object_storage.py`
- Test: `tests/unit/app/test_object_storage.py`

- [ ] Write failing tests for masked public config, preserving an existing secret when the update payload uses `********`, generating OSS object keys under a normalized prefix, and producing signed GET URLs.
- [ ] Run `pytest tests/unit/app/test_object_storage_module.py -q` and confirm the new tests fail because the module does not exist.
- [ ] Implement `ObjectStorageConfig`, `ObjectStorageStore`, `AliyunOssClient`, and `get_object_storage_client()`.
- [ ] Run `pytest tests/unit/app/test_object_storage_module.py -q` and confirm the tests pass.

### Task 2: Admin Config Router

**Files:**
- Create: `src/qwenpaw/app/routers/object_storage.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Test: `tests/unit/routers/test_object_storage.py`

- [ ] Write failing tests for `GET /api/admin/object-storage/config`, `PUT /api/admin/object-storage/config`, and `POST /api/admin/object-storage/test`.
- [ ] Run `pytest tests/unit/routers/test_object_storage.py -q` and confirm the new tests fail.
- [ ] Add the admin router and include it under the existing admin API router.
- [ ] Run `pytest tests/unit/routers/test_object_storage.py -q` and confirm the tests pass.

### Task 3: AIGC Generated Asset Integration

**Files:**
- Modify: `src/qwenpaw/app/routers/aigc_studio.py`
- Test: `tests/unit/routers/test_aigc_studio.py`

- [ ] Write failing tests showing enabled OSS uploads generated image bytes, does not create the local generated file, keeps the existing asset route as `asset.url`, redirects asset file reads to a signed OSS URL, and converts an OSS-backed asset reference to a data URL.
- [ ] Run the targeted AIGC tests and confirm they fail for missing remote storage behavior.
- [ ] Integrate the object storage client into `_save_generated_asset()`, `_asset_file_response()`, and `_asset_to_image_data_url()`.
- [ ] Run the targeted AIGC tests and confirm they pass.

### Task 4: Admin Console Page

**Files:**
- Create: `console/src/pages/Settings/ObjectStorage/index.tsx`
- Create: `console/src/pages/Settings/ObjectStorage/index.module.less`
- Create: `console/src/pages/Settings/ObjectStorage/ObjectStorage.test.tsx`
- Modify: `console/src/layouts/AdminLayout/index.tsx`
- Modify: `console/src/layouts/Sidebar.tsx`
- Modify: `console/src/layouts/constants.ts`

- [ ] Write failing Vitest coverage for load, save, masked secret preservation, and test action.
- [ ] Run `npm run test:run -- ObjectStorage.test.tsx` from `console/` and confirm the test fails.
- [ ] Build the Object Storage settings page and add it to admin navigation.
- [ ] Run `npm run test:run -- ObjectStorage.test.tsx` from `console/` and confirm it passes.

### Task 5: Verification

**Files:**
- Existing targeted backend and frontend tests.

- [ ] Run `pytest tests/unit/app/test_object_storage_module.py tests/unit/routers/test_object_storage.py tests/unit/routers/test_aigc_studio.py -q`.
- [ ] Run `npm run test:run -- ObjectStorage.test.tsx` from `console/`.
- [ ] Run `npm exec -- tsc -b --noEmit` from `console/`.
- [ ] Report any failures exactly, including whether they are pre-existing or introduced by this work.
