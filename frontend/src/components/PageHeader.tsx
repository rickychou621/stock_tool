interface Props {
  title: string
  description: string
  eyebrow?: string
}
export function PageHeader({ title, description, eyebrow = '每日看盤' }: Props) {
  return (
    <header className="page-header">
      <span className="eyebrow">{eyebrow}</span>
      <h1>{title}</h1>
      <p>{description}</p>
    </header>
  )
}
