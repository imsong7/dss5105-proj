import type { CategoryKey } from "../domain/taxonomy";
import { CONTENT_CATEGORIES } from "../domain/taxonomy";

const CATEGORY_STYLES: Record<CategoryKey, string> = {
  medical: "bg-cat-medical-fg",
  promotional: "bg-cat-promotional-fg",
  career: "bg-cat-career-fg",
  canva: "bg-cat-canva-fg",
  general: "bg-cat-general-fg",
  others: "bg-cat-others-fg",
};

const SIZES = {
  sm: "gap-1.5 text-[12px]",
  md: "gap-1.5 text-[13px]",
} as const;

interface CategoryBadgeProps {
  category: CategoryKey;
  size?: keyof typeof SIZES;
}

export function CategoryBadge({ category, size = "sm" }: CategoryBadgeProps) {
  return (
    <span
      className={`inline-flex items-center text-muted ${SIZES[size]}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${CATEGORY_STYLES[category]}`}
        aria-hidden="true"
      />
      <span>{CONTENT_CATEGORIES[category]}</span>
    </span>
  );
}
