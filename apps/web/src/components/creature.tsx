type Props = { kind: "lobster" | "crab" | "crayfish"; className?: string };

/** Original geometric characters. Palette comes entirely from named CSS tokens. */
export function Creature({ kind, className = "" }: Props) {
  const crab = kind === "crab";
  const banker = kind === "crayfish";
  return <svg viewBox="0 0 240 220" className={`creature creature--${kind} ${className}`} aria-hidden="true">
    <g className="chair"><path d="M65 210V117Q65 98 85 98H155Q175 98 175 117V210Z" /><path d="M73 207V125Q73 108 90 108H150Q167 108 167 125V207Z" /></g>
    <g className="shell-limbs" strokeWidth="8" strokeLinecap="round" fill="none">
      <path d={crab ? "M82 132 48 116 30 137M78 148 42 147 28 165M158 132 192 116 210 137M162 148 198 147 212 165" : "M93 142 66 154 54 180M92 159 70 176 63 195M147 142 174 154 186 180M148 159 170 176 177 195"} />
    </g>
    {!crab && <g className="shell-tail"><path d="M99 164Q86 202 104 215L120 205L136 215Q154 202 141 164Z" /><path d="M103 181H137M103 192H137M107 203H133" className="shell-line" /></g>}
    <g className="shell-arms" strokeWidth="13" strokeLinecap="round" fill="none"><path d="M88 128Q51 125 48 87" /><path d="M152 128Q189 125 192 87" /></g>
    <g className="shell-claws"><path d="M45 96C15 91 13 53 35 43L44 66L52 37C78 55 75 87 45 96Z" /><path d="M195 96C225 91 227 53 205 43L196 66L188 37C162 55 165 87 195 96Z" /></g>
    <g className="shell-body"><path d={crab ? "M68 116Q65 86 120 83Q175 86 172 116L159 151Q120 173 81 151Z" : "M94 100Q93 82 120 78Q147 82 146 100L151 146Q150 178 120 185Q90 178 89 146Z"} /></g>
    {!crab && <g className="antennae" fill="none" strokeWidth="3" strokeLinecap="round"><path d="M112 85Q93 43 79 39" /><path d="M128 85Q145 41 165 34" /></g>}
    <g className="eye-stalks" strokeWidth="8" strokeLinecap="round"><path d="M105 99 100 79M135 99 140 79" /></g>
    <g className="eyes"><circle cx="100" cy="78" r="9" /><circle cx="140" cy="78" r="9" /></g>
    <g className="pupils"><circle cx="102" cy="78" r="4" /><circle cx="142" cy="78" r="4" /></g>
    {crab && <g className="glasses" fill="none" strokeWidth="3"><rect x="86" y="67" width="27" height="23" rx="6" /><rect x="127" y="67" width="27" height="23" rx="6" /><path d="M113 77H127" /></g>}
    <path d={crab ? "M110 122H130" : "M109 121Q120 130 132 119"} className="mouth" fill="none" strokeWidth="3" strokeLinecap="round" />
    <g className="suit"><path d="M89 138 111 147 120 174 129 147 151 138 157 205H83Z" /><path d="M104 140 120 151 136 140 129 171H111Z" className="shirt" /><path d="M117 153H123L127 175 120 181 113 175Z" className="tie" /></g>
    {banker && <><path d="M96 59H151L143 49H105Z" className="hat" /><rect x="105" y="26" width="38" height="28" rx="3" className="hat" /><path d="M106 46H142" className="hat-band" strokeWidth="5" /><circle cx="140" cy="78" r="13" className="monocle" fill="none" strokeWidth="2" /><path d="M153 78Q166 103 154 133" className="monocle" fill="none" strokeWidth="2" /></>}
    <g className="desk"><path d="M25 192H215L228 210H12Z" /><path d="M12 210H228V220H12Z" /></g>
    <path d="M93 196H147L141 204H99Z" className="desk-paper" />
  </svg>;
}

