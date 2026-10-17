import type { FC } from 'react';

/** Types for the React Bits DepthCarousel (JS + CSS variant, vendored unmodified in DepthCarousel.jsx). Verified against its source. */
export interface DepthCarouselItem {
  image: string;
  alt?: string;
  /** extra fields are carried through to `onChange` untouched */
  [extra: string]: unknown;
}
export interface DepthCarouselProps {
  items?: Array<DepthCarouselItem | string>;
  cardWidth?: number;
  cardHeight?: number;
  radius?: number;
  tint?: string;
  depth?: number;
  spread?: number;
  tilt?: number;
  tiltDirection?: 'left' | 'right';
  perspective?: number;
  visibleCards?: number;
  falloff?: number;
  blur?: number;
  /** milliseconds */
  duration?: number;
  ease?: string;
  autoplay?: boolean;
  autoplayDelay?: number;
  loop?: boolean;
  showControls?: boolean;
  showIndicators?: boolean;
  onChange?: (index: number, item: DepthCarouselItem) => void;
  className?: string;
}
declare const DepthCarousel: FC<DepthCarouselProps>;
export default DepthCarousel;
