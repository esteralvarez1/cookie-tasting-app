export async function triggerDownload(response: Response, fallbackFilename: string): Promise<void> {
  const disposition = response.headers.get('content-disposition') ?? '';
  const match = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
  const filename = match ? match[1].replace(/['"]/g, '').trim() : fallbackFilename;

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

export function buildFallbackFilename(blockId: string, format: string): string {
  const date = new Date().toISOString().slice(0, 10);
  return `${blockId}_${date}.${format}`;
}
