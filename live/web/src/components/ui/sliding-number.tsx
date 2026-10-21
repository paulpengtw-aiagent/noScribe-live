// Source: https://github.com/barvian/number-flow (npm: @number-flow/react 0.6.2, licence MIT; repo LICENSE and npm "license" field checked 2026-10-21).
// Installed with `pnpm add @number-flow/react`, not via the shadcn CLI. This file is a thin wrapper
// that gives the stat cards one stable import path. Load it lazily (React.lazy) to keep first-load JS small.
import NumberFlow from "@number-flow/react"
import type { ComponentProps } from "react"

export type SlidingNumberProps = ComponentProps<typeof NumberFlow>

export function SlidingNumber(props: SlidingNumberProps) {
  return <NumberFlow {...props} />
}

export default SlidingNumber
