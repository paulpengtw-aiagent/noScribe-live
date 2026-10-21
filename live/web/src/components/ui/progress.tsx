import * as React from "react"
import { cn } from "cn"
import { Progress as ProgressPrimitive } from "radix-ui"

function Progress({
  className,
  value,
  live = false,
  ...props
}: React.ComponentProps<typeof ProgressPrimitive.Root> & {
  /** The run is live: the Frost fill carries a slow sheen. Off by default; reduced motion and Easy view hide it. */
  live?: boolean
}) {
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      className={cn(
        "relative flex h-1 w-full items-center overflow-x-hidden rounded-full bg-muted",
        className
      )}
      {...props}
    >
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        data-live={live ? "true" : undefined}
        className="progress-frost size-full flex-1 transition-all"
        style={{
          transform: `translateX(-${100 - (value || 0)}%)`,
          // The Frost gradient fills the visible part of the indicator, its right-hand value% of the width.
          backgroundSize: `${value || 0}% 100%`,
          backgroundPosition: "100% 0",
        }}
      />
    </ProgressPrimitive.Root>
  )
}

export { Progress }
