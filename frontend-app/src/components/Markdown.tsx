import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Rendu Markdown sécurisé (sans HTML brut) pour les énoncés de devoirs et les
 * livrables. Les liens s'ouvrent dans un nouvel onglet. Le style est porté par
 * la classe CSS `.markdown-body`.
 */
export function Markdown({ children, className = "" }: { children?: string | null; className?: string }) {
  if (!children || !children.trim()) return null;
  return (
    <div className={`markdown-body ${className}`.trim()}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
