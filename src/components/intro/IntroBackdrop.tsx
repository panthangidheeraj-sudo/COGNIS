/**
 * The intro's living background: warm ivory with a slow orbital line-work, a few flowing contour lines and two drifting highlights.
 * Pure CSS transforms on four layers (no canvas, no WebGL, no script): the work per frame is compositing only, and `intro.css` turns every
 * animation off under reduced motion and hides the heavier layers on small screens.
 */
export function IntroBackdrop() {
  return (
    <div className="li-bg" aria-hidden data-testid="intro-backdrop">
      <span className="li-glow li-glow--a" />
      <span className="li-glow li-glow--b" />
      <div className="li-orbits">
        <svg viewBox="0 0 1200 1200" fill="none">
          <g strokeWidth="1.4">
            <ellipse cx="600" cy="600" rx="560" ry="214" transform="rotate(-22 600 600)" stroke="#0f1b2a" strokeOpacity="0.09" />
            <ellipse cx="600" cy="600" rx="470" ry="330" transform="rotate(18 600 600)" stroke="#b08d4a" strokeOpacity="0.3" />
            <ellipse cx="600" cy="600" rx="380" ry="138" transform="rotate(-52 600 600)" stroke="#0f1b2a" strokeOpacity="0.07" />
            <circle cx="600" cy="600" r="292" stroke="#b08d4a" strokeOpacity="0.16" strokeDasharray="2 9" />
            <circle cx="600" cy="600" r="150" stroke="#0f1b2a" strokeOpacity="0.06" />
          </g>
          <g fill="#b08d4a">
            <circle cx="1002" cy="437" r="5" fillOpacity="0.55" />
            <circle cx="203" cy="741" r="4" fillOpacity="0.4" />
            <circle cx="889" cy="260" r="3.5" fillOpacity="0.35" />
          </g>
        </svg>
      </div>
      <div className="li-contours">
        <svg viewBox="0 0 1600 600" preserveAspectRatio="none" fill="none">
          <path d="M0 330 C 220 230 420 440 640 340 S 1040 220 1260 330 S 1520 410 1600 340" stroke="#b08d4a" strokeOpacity="0.2" strokeWidth="1.3" />
          <path d="M0 372 C 240 272 440 482 660 382 S 1060 262 1280 372 S 1540 452 1600 382" stroke="#0f1b2a" strokeOpacity="0.07" strokeWidth="1.2" />
          <path d="M0 414 C 260 314 460 524 680 424 S 1080 304 1300 414 S 1560 494 1600 424" stroke="#b08d4a" strokeOpacity="0.14" strokeWidth="1.1" />
          <path d="M0 456 C 280 356 480 566 700 466 S 1100 346 1320 456 S 1580 536 1600 466" stroke="#0f1b2a" strokeOpacity="0.05" strokeWidth="1" />
        </svg>
      </div>
    </div>
  );
}
