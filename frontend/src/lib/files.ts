const objectUrls = new Set<string>();
export function createFileUrl(file: File) {
  const url = URL.createObjectURL(file);
  objectUrls.add(url);
  return url;
}
export function releaseFileUrl(url?: string) {
  if (url && objectUrls.has(url)) {
    URL.revokeObjectURL(url);
    objectUrls.delete(url);
  }
}
export function releaseAllFileUrls() {
  objectUrls.forEach((url) => URL.revokeObjectURL(url));
  objectUrls.clear();
}
export function imageDimensions(
  url: string,
): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () =>
      resolve({ width: image.naturalWidth, height: image.naturalHeight });
    image.onerror = () =>
      reject(new Error("Không thể đọc ảnh. File có thể bị hỏng."));
    image.src = url;
  });
}
