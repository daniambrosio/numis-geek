export default function CountryFlag({ country }: { country: string }) {
  const flag = country === 'BR' ? '🇧🇷' : country === 'US' ? '🇺🇸' : '🌐'
  return <span className="text-[11px] leading-none">{flag}</span>
}
