/**
 * Spec 61c — Efficient frontier chart (SVG, no recharts).
 * X = annualized volatility, Y = annualized expected return.
 * Plots the frontier path + 2 marker dots: current and optimal portfolios.
 */
import type { FrontierPointOut } from '../lib/api'

interface Props {
  frontier: FrontierPointOut[]
  currentPoint?: { ret: number; vol: number } | null
  optimalPoint?: { ret: number; vol: number } | null
  width?: number
  height?: number
}

function fmtPct(n: number): string {
  return `${(n * 100).toFixed(1)}%`
}

export default function EfficientFrontierChart({
  frontier, currentPoint, optimalPoint,
  width = 480, height = 280,
}: Props) {
  const allPoints: { ret: number; vol: number }[] = [...frontier]
  if (currentPoint) allPoints.push(currentPoint)
  if (optimalPoint) allPoints.push(optimalPoint)

  if (allPoints.length === 0) {
    return (
      <div className="text-[12px] text-gray-500 dark:text-gray-400 italic py-8 text-center">
        Sem pontos de fronteira eficiente disponíveis.
      </div>
    )
  }

  const padding = 40
  const minVol = Math.min(...allPoints.map((p) => p.vol))
  const maxVol = Math.max(...allPoints.map((p) => p.vol))
  const minRet = Math.min(...allPoints.map((p) => p.ret))
  const maxRet = Math.max(...allPoints.map((p) => p.ret))
  // small padding to keep markers off the axis lines
  const volRange = Math.max(maxVol - minVol, 1e-6) * 1.05
  const retRange = Math.max(maxRet - minRet, 1e-6) * 1.05

  function xOf(vol: number): number {
    return padding + ((vol - minVol) / volRange) * (width - 2 * padding)
  }
  function yOf(ret: number): number {
    return height - padding - ((ret - minRet) / retRange) * (height - 2 * padding)
  }

  // Frontier path: sort by vol so the polyline is monotone.
  const sortedFrontier = [...frontier].sort((a, b) => a.vol - b.vol)
  const pathD = sortedFrontier
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${xOf(p.vol)} ${yOf(p.ret)}`)
    .join(' ')

  // 4 evenly spaced gridlines (axis labels).
  const xTicks = 4
  const yTicks = 4
  const xLabels = Array.from({ length: xTicks }, (_, i) =>
    minVol + (volRange / 1.05) * (i / (xTicks - 1)),
  )
  const yLabels = Array.from({ length: yTicks }, (_, i) =>
    minRet + (retRange / 1.05) * (i / (yTicks - 1)),
  )

  return (
    <div data-testid="frontier-chart" className="relative">
      <svg width={width} height={height} className="overflow-visible">
        {/* Y gridlines + labels */}
        {yLabels.map((v, i) => (
          <g key={`y-${i}`}>
            <line
              x1={padding} x2={width - padding}
              y1={yOf(v)} y2={yOf(v)}
              stroke="currentColor"
              className="text-gray-200 dark:text-gray-800"
              strokeDasharray="2,2"
            />
            <text
              x={padding - 6} y={yOf(v) + 3}
              textAnchor="end"
              className="text-[10px] fill-current text-gray-500 dark:text-gray-400 tnum"
            >
              {fmtPct(v)}
            </text>
          </g>
        ))}
        {/* X labels */}
        {xLabels.map((v, i) => (
          <text
            key={`x-${i}`}
            x={xOf(v)} y={height - padding + 14}
            textAnchor="middle"
            className="text-[10px] fill-current text-gray-500 dark:text-gray-400 tnum"
          >
            {fmtPct(v)}
          </text>
        ))}
        {/* Axes */}
        <line
          x1={padding} y1={height - padding}
          x2={width - padding} y2={height - padding}
          stroke="currentColor" className="text-gray-400 dark:text-gray-600"
        />
        <line
          x1={padding} y1={padding}
          x2={padding} y2={height - padding}
          stroke="currentColor" className="text-gray-400 dark:text-gray-600"
        />
        {/* Frontier path */}
        {sortedFrontier.length > 1 && (
          <path
            d={pathD} fill="none" strokeWidth="2"
            stroke="currentColor"
            className="text-indigo-500 dark:text-indigo-400"
          />
        )}
        {/* Frontier point dots */}
        {sortedFrontier.map((p, i) => (
          <circle
            key={`fp-${i}`}
            cx={xOf(p.vol)} cy={yOf(p.ret)} r="2"
            fill="currentColor"
            className="text-indigo-400 dark:text-indigo-500"
          />
        ))}
        {/* Current portfolio marker */}
        {currentPoint && (
          <g>
            <circle
              data-testid="current-marker"
              cx={xOf(currentPoint.vol)} cy={yOf(currentPoint.ret)} r="6"
              fill="currentColor"
              className="text-red-500"
            />
            <text
              x={xOf(currentPoint.vol) + 9} y={yOf(currentPoint.ret) + 4}
              className="text-[10px] fill-current text-red-600 dark:text-red-300 font-medium"
            >
              atual
            </text>
          </g>
        )}
        {/* Optimal portfolio marker */}
        {optimalPoint && (
          <g>
            <circle
              data-testid="optimal-marker"
              cx={xOf(optimalPoint.vol)} cy={yOf(optimalPoint.ret)} r="6"
              fill="currentColor"
              className="text-emerald-500"
            />
            <text
              x={xOf(optimalPoint.vol) + 9} y={yOf(optimalPoint.ret) + 4}
              className="text-[10px] fill-current text-emerald-700 dark:text-emerald-300 font-medium"
            >
              sugerido
            </text>
          </g>
        )}
      </svg>
      <div className="absolute bottom-1 right-2 text-[9px] text-gray-500 dark:text-gray-500">
        eixo X: volatilidade anual · eixo Y: retorno anual esperado
      </div>
    </div>
  )
}
