import { Badge } from "@/components/ui/badge";

type NoticeVariant = "success" | "warning" | "destructive" | "info";

const noticeStyles: Record<NoticeVariant, string> = {
  success: "border-emerald-200 bg-emerald-50 text-emerald-950",
  warning: "border-amber-200 bg-amber-50 text-amber-950",
  destructive: "border-red-200 bg-red-50 text-red-950",
  info: "border-sky-200 bg-sky-50 text-sky-950",
};

export function Notice({
  children,
  variant = "success",
}: {
  children: React.ReactNode;
  variant?: NoticeVariant;
}) {
  return (
    <div
      role={variant === "destructive" ? "alert" : "status"}
      className={`rounded-xl border p-3.5 text-sm ${noticeStyles[variant]}`}
    >
      {children}
    </div>
  );
}
export function Status({ value }: { value: string }) {
  return (
    <Badge
      variant="outline"
      className={
        value === "REVIEW_QUEUE"
          ? "border-amber-300 bg-amber-50 text-amber-900"
        : value === "REJECTED" || value === "FAILED"
            ? "border-red-300 bg-red-50 text-red-900"
            : value === "AMENDED"
              ? "border-sky-200 bg-sky-50 text-sky-900"
              : "border-emerald-200 bg-emerald-50 text-emerald-900"
      }
    >
      {value.replaceAll("_", " ")}
    </Badge>
  );
}
