import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { Dispatch, ReactNode, SetStateAction } from "react";
import { Popover } from "radix-ui";
import { Eye, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { amount } from "@/lib/api";
import type { Row } from "@/lib/api";

const PreviewContext = createContext<{
  activeId: string | null;
  setActiveId: Dispatch<SetStateAction<string | null>>;
} | null>(null);

/** One active preview per list, including previews pinned by keyboard/touch. */
export function ReceiptPreviewProvider({ children }: { children: ReactNode }) {
  const [activeId, setActiveId] = useState<string | null>(null);
  return (
    <PreviewContext.Provider value={{ activeId, setActiveId }}>
      {children}
    </PreviewContext.Provider>
  );
}

function usePreviewGroup() {
  const group = useContext(PreviewContext);
  if (!group) throw new Error("Receipt previews require a list provider");
  return group;
}

/** Supplemental preview. Open receipt remains the primary evidence/review action. */
export function ReceiptPreview({
  row,
  token,
  onOpen,
}: {
  row: Row;
  token: string;
  onOpen: () => void;
}) {
  const { activeId, setActiveId } = usePreviewGroup();
  const open = activeId === row.receipt_id;
  const [placement, setPlacement] = useState<{
    side: "top" | "bottom" | "left" | "right";
    height: number;
    width: number;
  }>({ side: "bottom", height: 380, width: 288 });
  const trigger = useRef<HTMLButtonElement>(null);
  const openingPosition = useRef<{
    top: number;
    left: number;
    width: number;
    height: number;
  } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hovered = useRef(false);
  function cancel() {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  }
  function close() {
    cancel();
    // A timer from the previous receipt must never close its replacement.
    setActiveId((current) => (current === row.receipt_id ? null : current));
  }
  function show() {
    const rect = trigger.current?.getBoundingClientRect();
    if (!rect) return;
    openingPosition.current = {
      top: rect.top,
      left: rect.left,
      width: document.documentElement.clientWidth,
      height: document.documentElement.clientHeight,
    };
    const above = Math.max(0, rect.top - 32);
    const below = Math.max(
      0,
      document.documentElement.clientHeight - rect.bottom - 32,
    );
    const side = below >= 380 || below >= above ? "bottom" : "top";
    // Measure once on opening: image decoding cannot change card size or side.
    if (Math.max(above, below) < 240) {
      // In short windows, fit beside the trigger so the fixed header and image
      // retain useful space without covering the trigger or creating a scrollbar.
      const left = Math.max(0, rect.left - 32);
      const right = Math.max(
        0,
        document.documentElement.clientWidth - rect.right - 32,
      );
      setPlacement({
        side: left >= right ? "left" : "right",
        width: Math.min(288, Math.max(left, right)),
        height: Math.min(380, document.documentElement.clientHeight - 32),
      });
    } else {
      setPlacement({
        side,
        height: Math.min(380, side === "bottom" ? below : above),
        width: 288,
      });
    }
    setActiveId(row.receipt_id);
  }
  function schedule(value: boolean) {
    cancel();
    timer.current = setTimeout(
      () => {
        timer.current = null;
        if (value) hovered.current = true;
        if (value) show();
        else close();
      },
      value ? 180 : 220,
    );
  }
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  useEffect(() => {
    if (!open) return;
    const dismiss = () => {
      const rect = trigger.current?.getBoundingClientRect(),
        initial = openingPosition.current;
      // Opening a scrolled-into-view row can deliver an already queued scroll event.
      // Only new movement should dismiss the card, not that stale notification.
      if (
        rect &&
        initial &&
        Math.abs(rect.top - initial.top) < 1 &&
        Math.abs(rect.left - initial.left) < 1 &&
        document.documentElement.clientWidth === initial.width &&
        document.documentElement.clientHeight === initial.height
      )
        return;
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
      setActiveId((current) => (current === row.receipt_id ? null : current));
    };
    // Moving the list invalidates the opening measurement; dismiss rather than jump.
    window.addEventListener("resize", dismiss);
    document.addEventListener("scroll", dismiss, true);
    return () => {
      window.removeEventListener("resize", dismiss);
      document.removeEventListener("scroll", dismiss, true);
    };
  }, [open, row.receipt_id, setActiveId]);
  return (
    <Popover.Root
      open={open}
      onOpenChange={(value) => {
        cancel();
        hovered.current = false;
        if (value) show();
        else close();
      }}
    >
      <Popover.Trigger asChild>
        <Button
          ref={trigger}
          variant="ghost"
          size="icon"
          aria-label={`Preview receipt ${row.vendor || row.receipt_id}`}
          onPointerEnter={(e) => {
            if (e.pointerType === "mouse" && !open) schedule(true);
          }}
          onPointerLeave={(e) => {
            if (e.pointerType === "mouse") {
              cancel();
              if (hovered.current) schedule(false);
            }
          }}
        >
          <Eye />
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className="receipt-preview z-50 flex w-72 max-w-[calc(100vw-2rem)] flex-col gap-3 rounded-xl border bg-white p-3 shadow-xl"
          style={{ height: placement.height, width: placement.width }}
          side={placement.side}
          align="end"
          sideOffset={10}
          collisionPadding={16}
          collisionBoundary={document.documentElement}
          aria-label={`Receipt preview for ${row.vendor || row.receipt_id}`}
          onOpenAutoFocus={(e) => {
            if (hovered.current) e.preventDefault();
          }}
          onCloseAutoFocus={(e) => {
            if (
              hovered.current ||
              (activeId !== null && activeId !== row.receipt_id)
            )
              e.preventDefault();
          }}
          onPointerEnter={cancel}
          onPointerLeave={() => {
            if (hovered.current) schedule(false);
          }}
          onFocusCapture={() => {
            cancel();
            hovered.current = false;
          }}
        >
          <div
            className="flex h-12 shrink-0 items-start justify-between gap-2"
            data-slot="preview-header"
          >
            <div className="min-w-0 flex-1">
              <h2
                className="truncate text-sm leading-5 font-semibold"
                title={row.vendor || "Receipt preview"}
              >
                {row.vendor || "Receipt preview"}
              </h2>
              <p className="muted mt-1 truncate leading-5">
                {amount(row.total_amount, row.currency)}
              </p>
            </div>
            <Popover.Close asChild>
              <Button
                size="icon"
                variant="ghost"
                className="shrink-0"
                aria-label="Close receipt preview"
              >
                <X />
              </Button>
            </Popover.Close>
          </div>
          {/* Radix keeps content mounted during exit. Keep the image and its URL
              alive for that entire animation, then clean up on actual unmount. */}
          <PreviewImage id={row.receipt_id} token={token} />
          <Button
            variant="outline"
            className="w-full shrink-0"
            onClick={() => {
              close();
              onOpen();
            }}
          >
            Open full receipt
          </Button>
          <Popover.Arrow className="fill-white" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function PreviewImage({ id, token }: { id: string; token: string }) {
  const [image, setImage] = useState(""),
    [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let url = "";
    fetch(`/receipts/${id}/preview`, {
      headers: { "X-API-Key": token },
      cache: "no-store",
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]),
    })
      .then(async (response) => {
        if (
          !response.ok ||
          !["image/jpeg", "image/png"].includes(
            response.headers.get("content-type")?.split(";")[0] || "",
          )
        )
          throw new Error("Image unavailable");
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        url = URL.createObjectURL(blob);
        setImage(url);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(true);
      });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [id, token]);
  return (
    <div
      className="flex min-h-0 flex-1 items-center justify-center overflow-hidden rounded-lg border bg-muted p-2"
      data-slot="preview-image"
    >
      {error ? (
        <p className="muted line-clamp-3 text-center">
          Preview unavailable. Open the saved record for details.
        </p>
      ) : image ? (
        <img
          src={image}
          alt="Quick preview of original receipt"
          loading="lazy"
          className="h-full w-full object-contain"
          onError={() => setError(true)}
        />
      ) : (
        <p role="status" className="muted p-4">
          Loading preview…
        </p>
      )}
    </div>
  );
}
