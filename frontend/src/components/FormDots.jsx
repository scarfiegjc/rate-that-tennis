export default function FormDots({ dots = [], max = 10 }) {
  const visible = dots.slice(0, max)
  return (
    <div className="form-dots" title={visible.join(' ')}>
      {visible.map((d, i) => (
        <div key={i} className={`form-dot ${d}`} />
      ))}
    </div>
  )
}
