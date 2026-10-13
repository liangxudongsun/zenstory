import type { ReactNode } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "../ui/Button";

interface AdminPageStateProps {
  isLoading?: boolean;
  isFetching?: boolean;
  isError?: boolean;
  isEmpty?: boolean;
  loadingText?: string;
  errorText?: string;
  emptyText?: string;
  retryText?: string;
  onRetry?: () => void;
  stateClassName?: string;
  children: ReactNode;
}

const DEFAULT_STATE_CLASS =
  "admin-surface flex min-h-[220px] items-center justify-center px-4 py-12";

export function AdminPageState({
  isLoading = false,
  isFetching = false,
  isError = false,
  isEmpty = false,
  loadingText,
  errorText,
  emptyText,
  retryText,
  onRetry,
  stateClassName = DEFAULT_STATE_CLASS,
  children,
}: AdminPageStateProps) {
  const { t } = useTranslation();
  const resolvedLoadingText = loadingText ?? t('common:loading');
  const resolvedErrorText = errorText ?? t('common:error');
  const resolvedEmptyText = emptyText ?? t('common:noData');
  const resolvedRetryText = retryText ?? t('common:retry');

  if (isLoading || (isFetching && isEmpty)) {
    return (
      <div className={stateClassName} role="status" aria-live="polite">
        <div className="flex flex-col items-center gap-3">
          <Loader2 aria-hidden="true" className="h-5 w-5 animate-spin text-[var(--admin-accent-text)]" />
          <div className="text-[hsl(var(--text-secondary))]">{resolvedLoadingText}</div>
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className={stateClassName}>
        <div className="flex max-w-lg flex-col items-center gap-3 text-center">
          <div role="alert" className="flex flex-col items-center gap-3 text-[hsl(var(--error-text))]"><AlertCircle size={24} aria-hidden="true" />{resolvedErrorText}</div>
          {onRetry && (
            <Button
              type="button"
              onClick={onRetry}
              variant="secondary"
              size="touch"
            >
              {resolvedRetryText}
            </Button>
          )}
        </div>
      </div>
    );
  }

  if (isEmpty) {
    return (
      <div className={stateClassName}>
        <div className="text-[hsl(var(--text-secondary))]">{resolvedEmptyText}</div>
      </div>
    );
  }

  return <>{children}</>;
}
