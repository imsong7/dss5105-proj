import type { CategoryKey } from "../domain/taxonomy";
import { CONTENT_CATEGORIES } from "../domain/taxonomy";

const CATEGORY_STYLES: Record<CategoryKey, string> = {
  medical: "border-cat-medical-line bg-cat-medical-bg text-cat-medical-fg",
  promotional:
    "border-cat-promotional-line bg-cat-promotional-bg text-cat-promotional-fg",
  career: "border-cat-career-line bg-cat-career-bg text-cat-career-fg",
  canva: "border-cat-canva-line bg-cat-canva-bg text-cat-canva-fg",
  general: "border-cat-general-line bg-cat-general-bg text-cat-general-fg",
  others: "border-cat-others-line bg-cat-others-bg text-cat-others-fg",
};

const SIZES = {
  sm: "gap-1.5 px-2 py-[3px] text-[11px]",
  md: "gap-1.5 px-2.5 py-1 text-[13px]",
} as const;

interface CategoryBadgeProps {
  category: CategoryKey;
  size?: keyof typeof SIZES;
}

export function CategoryBadge({ category, size = "sm" }: CategoryBadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full border font-medium ${CATEGORY_STYLES[category]} ${SIZES[size]}`}
    >
      <span
        className="h-1.5 w-1.5 rounded-full bg-current opacity-70"
        aria-hidden="true"
      />
      <span>{CONTENT_CATEGORIES[category]}</span>
    </span>
  );
}
