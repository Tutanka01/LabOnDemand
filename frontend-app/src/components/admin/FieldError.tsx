import { useI18n } from "../../lib/i18n";

/**
 * Inline validation message under a form field. `message` is either a translation key
 * (the admin dialogs put keys in their zod schemas) or a plain message from zod defaults.
 */
export function FieldError({ message }: { message?: string }) {
  const { t } = useI18n();
  if (!message) return null;
  return (
    <span className="badge red" role="alert">
      {t(message)}
    </span>
  );
}
