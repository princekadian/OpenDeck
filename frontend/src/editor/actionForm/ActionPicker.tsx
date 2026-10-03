import type { EditorTree } from "../api";

interface Props {
  id: string;
  tree: EditorTree;
  value: string;
  onChange: (actionType: string) => void;
  /** Hide these action types (e.g. composites inside a Multi Action). */
  exclude?: Set<string>;
  ariaLabel?: string;
}

/**
 * The action menu, generated from the backend registry: one group per category,
 * in registry order. Coming-soon actions are listed but cannot be chosen.
 */
export function ActionPicker({ id, tree, value, onChange, exclude, ariaLabel }: Props) {
  return (
    <select id={id} className="input" value={value} aria-label={ariaLabel} onChange={(e) => onChange(e.target.value)}>
      {tree.categories.map((category) => {
        const actions = tree.actions.filter((a) => a.category === category.id && !exclude?.has(a.type));
        if (actions.length === 0) return null;
        return (
          <optgroup key={category.id} label={category.label}>
            {actions.map((a) => (
              <option key={a.type} value={a.type} disabled={a.status !== "available"}>
                {a.status === "available" ? a.displayName : `${a.displayName} (coming soon)`}
              </option>
            ))}
          </optgroup>
        );
      })}
    </select>
  );
}
