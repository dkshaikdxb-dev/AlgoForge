export default function PageHeader({ overline, title, description, actions }) {
  return (
    <div className="px-8 py-7 border-b border-[var(--border)] flex items-start justify-between gap-6 hero-overlay">
      <div>
        <div className="overline">{overline}</div>
        <h1 className="font-display text-4xl sm:text-5xl mt-1 tracking-tight">{title}</h1>
        {description && (
          <p className="txt-secondary mt-2 max-w-2xl text-sm">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  );
}
