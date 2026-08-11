import type { SVGProps } from "react";

/**
 * Plane + dollar sign, one glyph: a $ (S-swoosh + vertical bar) with a
 * plane nose ascending off the top stroke - investment taking off.
 * Single color (currentColor), no gradients. Geometry is duplicated in
 * public/icon.svg (favicon) - keep both in sync if this changes.
 */
export function BrandMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
      <g
        stroke="currentColor"
        strokeWidth="2.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        transform="translate(12 12) scale(0.85) translate(-12 -12)"
      >
        <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
        <line x1="12" y1="1" x2="12" y2="23" />
      </g>
      <g fill="currentColor" transform="translate(9 -2.5) rotate(-20)">
        <path d="M2 12 L22 2 L14 12 L22 22 Z" transform="scale(0.5)" />
      </g>
    </svg>
  );
}
