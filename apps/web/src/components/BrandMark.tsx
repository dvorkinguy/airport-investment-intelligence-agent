import type { SVGProps } from "react";

/**
 * Plane mark - single color (currentColor), no gradients. Geometry is
 * duplicated in public/icon.svg (favicon) - keep both in sync if this
 * changes.
 */
export function BrandMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" {...props}>
      <path d="M21.5 15.5v-2l-8-5V3.06c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5V8.5l-8 5v2l8-2.5v5.5l-2 1.5V21.5l3.5-1 3.5 1v-1.5l-2-1.5V13l8 2.5z" />
    </svg>
  );
}
