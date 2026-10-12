# Bộ ảnh teal — prompt và file đã tích hợp

Chế độ: **built-in image generation/edit**, chỉnh sửa từng ảnh nguồn với `referenced_image_paths`, `transparent_background: true`. Mỗi ảnh được đổi sang teal và giữ bố cục của ảnh nguồn; không dùng CLI/API bên ngoài. PNG tạo ra được chép nguyên vào frontend, không chỉnh màu bằng xử lý ảnh sau đó.

## logo-teal.png

- Ảnh nguồn trước cập nhật: `frontend/public/assets/logo.png`.
- File trong gói: `frontend/public/assets/logo-teal.png`.
- Prompt cuối cùng:

```text
Use case: precise-object-edit. Edit target: the supplied Medical AI lung network logo. Change only the blue/indigo palette to a coherent teal palette centered on #008B8B and #007878, with pale aqua #B2DFDB and white. Preserve the exact recognizable paired-lung silhouette, trachea, smooth geometric layered shapes and six white network nodes connected inside the lungs. Keep it clean and readable as a small sidebar logo. Preserve composition and geometry, sharp clean edges. Remove all royal blue, purple and indigo hues; do not shift toward grass green or emerald. No text, no border tile, no watermark, genuinely transparent background.
```

## lung-knowledge-teal.png

- Ảnh nguồn trước cập nhật: `frontend/public/assets/lung-knowledge-v2.png`.
- File trong gói: `frontend/public/assets/lung-knowledge-teal.png`.
- Prompt cuối cùng:

```text
Use case: precise-object-edit. Edit target: the supplied polished 3D glass lung knowledge illustration. Recolor all blue, indigo and violet surfaces into a coordinated teal palette centered on #008B8B, deep teal #007878, pale aqua #B2DFDB and soft white. Preserve the two glass lungs, white branching airways, surrounding connected knowledge spheres, small white document in the lower right, proportions, camera angle and composition. Maintain elegant soft studio lighting and polished translucent glass, easy to read on an almost-white website. Keep the illustration conceptual and decorative. No letters or readable text, no new objects, no royal blue, purple, grass green or watermark. Genuinely transparent background with clean alpha edges.
```

## record-analysis-teal.png

- Ảnh nguồn trước cập nhật: `frontend/public/assets/record-analysis.png`.
- File trong gói: `frontend/public/assets/record-analysis-teal.png`.
- Prompt cuối cùng:

```text
Use case: precise-object-edit. Edit target: supplied 3D medical record analysis illustration. Recolor blue/indigo/purple lung icon, document accents, magnifying glass rim and handle, connecting lines and network spheres to a consistent teal palette centered on #008B8B and #007878, with pale aqua #B2DFDB and white. Keep all existing document sheets, small lung silhouette, magnifying glass, knowledge cards and linked spheres in the same positions and proportions. Preserve the soft polished 3D glass/plastic style, white papers and subtle grounding shadow. Match a teal medical assistant website. No readable letters, no new objects, no royal blue, indigo, purple or grass green. No watermark; genuinely transparent background.
```

## chat-welcome-teal.png

- Ảnh nguồn trước cập nhật: `frontend/public/assets/chat-welcome-v2.png`.
- File trong gói: `frontend/public/assets/chat-welcome-teal.png`.
- Prompt cuối cùng:

```text
Use case: precise-object-edit. Edit target: supplied polished 3D chat welcome illustration. Change only the blue/indigo color palette to coordinated teal centered on #008B8B and #007878, with pale aqua #B2DFDB and soft white. Preserve the overlapping two glass speech bubbles with three dots, the small pair of lungs in the lower right and the connected network spheres. Keep composition, proportions, soft polished 3D glass style, studio lighting and white foreground bubble. Make accents unmistakably teal, balanced blue-green rather than grass green. No royal blue, violet or indigo hues, no letters, new objects or watermark. Preserve genuinely transparent background and clean alpha edges.
```

