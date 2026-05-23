/** Mirror of prototypes/index.html `Sparkline` (line 872). Same line + filled
 * area below; same default colors. */

interface Props {
  data: number[]
  w?: number
  h?: number
  color?: string
  filled?: boolean
}

export default function Sparkline({
  data, w = 1200, h = 180, color = '#818cf8', filled = true,
}: Props) {
  if (!data || !data.length) return null
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const stepX = w / (data.length - 1)
  const pts = data.map((v, i) => `${(i * stepX).toFixed(2)},${(h - ((v - min) / range) * h).toFixed(2)}`)
  const path = 'M ' + pts.join(' L ')
  const areaPath = path + ` L ${w},${h} L 0,${h} Z`
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="w-full overflow-visible">
      {filled && <path d={areaPath} fill={color} fillOpacity="0.12" />}
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
