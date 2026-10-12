import { GlobeCanvas, type GlobeCanvasProps } from './GlobeCanvas';
import { createEarthSurface } from './surfaces/earthSurface';

/** The natural Blue Marble Earth. Lazy-loaded; only the About story mounts it. */
export default function EarthGlobe(props: GlobeCanvasProps) {
  return <GlobeCanvas {...props} surface={createEarthSurface} />;
}
