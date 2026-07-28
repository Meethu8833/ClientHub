import { Button } from "./Button";

// Every query error's face (design doc §4.1): apologize briefly, offer Retry.
// Never show raw error objects — they leak internals and help nobody.
export function ErrorState({ message = "Something went wrong loading this data.", onRetry }) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-center"
    >
      <p className="text-sm text-red-700">{message}</p>
      {onRetry && (
        <Button variant="secondary" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
