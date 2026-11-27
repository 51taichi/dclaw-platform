# storyai-3d-director-desk source note

## Upstream

- Repository: https://github.com/jiguang132/storyai-3d-director-desk
- Inspected commit: `8c8bd361790be4d37158a7430365e65546e358fe`
- Upstream package name: `storyai-3d-director-desk-demo`
- Upstream license: MIT

## Local use

The AIGC Studio integration does not add the upstream repository as a submodule and does not embed the full demo application. The first Director Stage MVP adapts these upstream product and code ideas into node-scoped AIGC Studio modules:

- scene project JSON schema
- 3D canvas editor layout
- model loading through React Three Fiber and Drei
- camera capture workflow
- capture result handoff to the host application

The implementation intentionally omits the upstream long-term `localStorage` persistence path. Director Stage project data is stored on `AigcCanvasNode.data.directorStageProject`, and camera captures are uploaded through the existing AIGC asset upload path.

## Imported assets

The first MVP imports only the audited mannequin model below:

- Target file: `console/public/models/director-stage/ue-mannequin-retopology.glb`
- License note: `console/public/models/director-stage/ue-mannequin-retopology.license.txt`
- Title: UE Mannequin (Retopology)
- Author: William Luque
- Source: https://sketchfab.com/3d-models/ue-mannequin-retopology-5394d9f894374a2ab7c57a21929ce4c2
- License: Sketchfab Standard

The upstream MIT license text is preserved at `console/public/models/director-stage/storyai-3d-director-desk.MIT-LICENSE.txt`.

## Verification snapshot

The temporary upstream clone was inspected outside this repository and was not retained as a submodule.

- `npm run build`: passed at the inspected commit. Vite emitted the upstream warning about several model-library thumbnail URLs being resolved at runtime, plus a chunk-size warning.
- `npm test`: 304 passed / 312 total. The 8 upstream failures were in model-library panel, viewport geometry, pose preset, and style assertions.

