import { Badge } from "@/components/ui/badge";
export function Notice({
  children,
  error = false,
}: {
  children: React.ReactNode;
  error?: boolean;
}) {
  return (
    <div
      role={error ? "alert" : "status"}
      className={`rounded-lg border p-3 text-sm ${error ? "border-red-200 bg-red-50 text-red-900" : "border-green-200 bg-green-50 text-green-900"}`}
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
            ? "border-red-200 bg-red-50 text-red-900"
            : "bg-green-50 text-green-900"
      }
    >
      {value.replaceAll("_", " ")}
    </Badge>
  );
}
