import { GlobeCanvas, type GlobeCanvasProps } from './GlobeCanvas';
import { createIntelSurface } from './surfaces/intelSurface';

/** The monochrome intelligence globe. Lazy-loaded; Home, Discover and the rest of the workspace mount it. */
export default function IntelGlobe(props: GlobeCanvasProps) {
  return <GlobeCanvas {...props} surface={createIntelSurface} />;
}
