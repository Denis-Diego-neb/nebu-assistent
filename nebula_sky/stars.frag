varying vec3 vColor;varying float vAlpha;
void main(){float r=length(gl_PointCoord-0.5)*2.0;float core=exp(-r*r*32.0),halo=exp(-r*r*5.0)*0.19;float a=(core+halo)*(1.0-smoothstep(0.7,1.0,r))*vAlpha;gl_FragColor=vec4(vColor*a,a);}
