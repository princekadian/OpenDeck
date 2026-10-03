import { BuiltinIcon, builtinIconName } from "./BuiltinIcon";


export function assetUrl(iconRef: string): string {
  return `/api/assets/${encodeURIComponent(iconRef.slice("asset:".length))}`;
}

interface Props {
  iconRef: string | null;
  /** Used when iconRef is empty: the action's default icon from the registry. */
  fallback?: string | null;
  className?: string;
}

/** Renders a button icon: built-in SVG, or an uploaded/extracted image. */
export function KeyIcon({ iconRef, fallback, className }: Props) {
  if (iconRef?.startsWith("asset:")) {
    return <img className={className} src={assetUrl(iconRef)} alt="" loading="lazy" decoding="async" draggable={false} />;
  }
  const name = builtinIconName(iconRef) ?? fallback ?? "key";
  return <BuiltinIcon name={name} className={className} />;
}
