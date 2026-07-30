import { Button } from "./Button";
import { Modal } from "./Modal";

// Every destructive action goes through this (design doc §4.1) — a real
// dialog, not window.confirm: styleable, focus-managed, and it can show a
// pending spinner while the DELETE request runs.
export function ConfirmDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel = "Delete",
  tone = "danger",
  isPending = false,
}) {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={title}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isPending}>
            Cancel
          </Button>
          <Button
            variant={tone === "danger" ? "danger" : "primary"}
            onClick={onConfirm}
            isLoading={isPending}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="text-sm text-gray-600 dark:text-gray-300">{message}</p>
    </Modal>
  );
}
