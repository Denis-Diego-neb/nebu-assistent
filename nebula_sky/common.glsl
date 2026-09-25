uniform sampler2D uNoise;
uniform vec3 uCamera;
uniform mat3 uRotation;
uniform vec2 uResolution;
uniform float uTime;
// Deriva do gas, calculada na CPU. Dentro do raymarch sao ~80 avaliacoes de
// fbm por pixel; um sin() aqui custaria centenas por quadro sem precisar.
uniform vec3 uDrift;
uniform vec3 uShear;
// Shared lens for gas and stars: ~58 degrees vertically (was ~70).
const float FOV_TAN=0.55;
float noise3(vec3 p) {
  vec3 i=floor(p),f=fract(p); f=f*f*(3.0-2.0*f);
  vec2 uv=i.xy+vec2(37.0,17.0)*i.z+f.xy;
  vec2 rg=texture2D(uNoise,(uv+0.5)/256.0).rg;
  return mix(rg.x,rg.y,f.z);
}
float fbm(vec3 p) {
  // E o cisalhamento entre as camadas que faz o gas parecer vivo; deslocar o
  // conjunto junto so pareceria camera se mexendo.
  return noise3(p+uDrift)*0.53+noise3(p*2.03+13.7-uShear)*0.27+
         noise3(p*4.11+29.1+uShear.zxy*1.7)*0.13+noise3(p*8.21+7.5-uDrift.yzx*2.3)*0.07;
}
float density(vec3 p) {
  vec3 q=p*1.04+vec3(5.4,8.1,3.7);
  float bend=noise3(q*0.43+uDrift*0.62)*1.35;
  float n=fbm(q+vec3(bend,-bend*0.6,bend*0.35));
  float billow=smoothstep(0.63,0.84,n);
  float channel=0.12+0.88*smoothstep(0.27,1.9,abs(p.x+0.48*sin(p.z*0.62)));
  return pow(billow,1.78)*channel*0.82;
}
vec3 pigment(vec3 p) {
  float region=0.5+0.5*sin(p.x*0.27+p.y*0.15+p.z*0.10+fbm(p*0.12)*2.0);
  float pockets=fbm(p*0.19+vec3(17.2,31.8,9.4));
  vec3 blue=vec3(0.035,0.22,1.0);
  vec3 violet=vec3(0.34,0.055,0.96);
  vec3 lilac=vec3(0.68,0.22,1.0);
  vec3 pink=vec3(1.0,0.09,0.57);
  vec3 red=vec3(1.0,0.025,0.075);
  vec3 color=mix(blue,violet,smoothstep(0.06,0.36,region));
  color=mix(color,pink,smoothstep(0.32,0.68,region));
  color=mix(color,red,smoothstep(0.64,0.96,region));
  color=mix(color,lilac,smoothstep(0.52,0.80,pockets)*0.28);
  return color;
}
