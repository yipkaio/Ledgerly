import { useEffect, useRef, useState } from "react";
import { Popover } from "radix-ui";
import { Eye, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { amount } from "@/lib/api";
import type { Row } from "@/lib/api";

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
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hovered = useRef(false);
  function cancel() {
    if (timer.current) clearTimeout(timer.current);
  }
  function schedule(value: boolean) {
    cancel();
    timer.current = setTimeout(
      () => {
        if (value) hovered.current = true;
        setOpen(value);
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
  return (
    <Popover.Root
      open={open}
      onOpenChange={(value) => {
        cancel();
        hovered.current = false;
        setOpen(value);
      }}
    >
      <Popover.Trigger asChild>
        <Button
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
          className="receipt-preview z-50 w-72 max-w-[calc(100vw-2rem)] rounded-xl border bg-white p-3 shadow-xl"
          side="bottom"
          align="end"
          sideOffset={10}
          collisionPadding={16}
          collisionBoundary={document.documentElement}
          aria-label={`Receipt preview for ${row.vendor || row.receipt_id}`}
          onOpenAutoFocus={(e) => {
            if (hovered.current) e.preventDefault();
          }}
          onCloseAutoFocus={(e) => {
            if (hovered.current) e.preventDefault();
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
          <div className="mb-3 flex items-start justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold">
                {row.vendor || "Receipt preview"}
              </h2>
              <p className="muted mt-0.5">
                {amount(row.total_amount, row.currency)}
              </p>
            </div>
            <Popover.Close asChild>
              <Button
                size="icon"
                variant="ghost"
                aria-label="Close receipt preview"
              >
                <X />
              </Button>
            </Popover.Close>
          </div>
          {open && <PreviewImage id={row.receipt_id} token={token} />}
          <Button
            variant="outline"
            className="mt-3 w-full"
            onClick={() => {
              setOpen(false);
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
    fetch(`/receipts/${id}/image`, {
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
    <div className="flex min-h-40 items-center justify-center overflow-hidden rounded-lg border bg-muted p-2">
      {error ? (
        <p className="muted p-4">
          Preview unavailable. Open the saved record for details.
        </p>
      ) : image ? (
        <img
          src={image}
          alt="Quick preview of original receipt"
          loading="lazy"
          className="max-h-64 max-w-full object-contain"
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
