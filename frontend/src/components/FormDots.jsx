export default function FormDots({ dots = [] }) {
  return (
    <div className="form-dots" title={dots.join(' ')}>
      {dots.map((d, i) => (
        <div key={i} className={`form-dot ${d}`} />
      ))}
    </div>
  )
}
