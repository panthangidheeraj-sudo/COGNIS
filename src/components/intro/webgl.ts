/** True when the browser can run the carousel (it needs WebGL2). jsdom and old browsers get the plain fallback. */
export function hasWebgl2(): boolean {
  if (typeof document === 'undefined' || typeof navigator === 'undefined' || /jsdom/i.test(navigator.userAgent)) return false;
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl2');
    gl?.getExtension('WEBGL_lose_context')?.loseContext();
    return !!gl;
  } catch {
    return false;
  }
}
