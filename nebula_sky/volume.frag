void main() {
  vec2 uv=(gl_FragCoord.xy*2.0-uResolution)/uResolution.y;
  vec3 ray=uRotation*normalize(vec3(uv*FOV_TAN,1.0));
  vec3 color=vec3(0.0);float transmission=1.0;
  for(int i=0;i<40;i++) {
    float t=0.20+(float(i)+0.5)*0.29;
    vec3 p=uCamera+ray*t;
    float d=density(p)*smoothstep(0.1,0.8,t)*(1.0-smoothstep(9.0,11.8,t));
    if(d>0.008) {
      float shadow=exp(-density(p+vec3(-0.35,0.48,-0.23))*3.8);
      float illumination=0.045+shadow*0.95;
      vec3 gas=pigment(p)*illumination;
      float rim=pow(max(0.0,1.0-d*2.5),3.0)*shadow;
      gas+=vec3(0.17,0.12,0.22)*rim*0.28;
      float alpha=1.0-exp(-d*0.29*1.15);
      color+=transmission*alpha*gas;
      transmission*=1.0-alpha;
    }
  }
  // Keep the UI's central reading area quieter, without modifying the world.
  vec2 screen=gl_FragCoord.xy/uResolution;
  float center=exp(-dot((screen-vec2(0.5,0.53))*vec2(3.5,5.0),(screen-vec2(0.5,0.53))*vec2(3.5,5.0)));
  color*=1.18-center*0.25;
  color=pow(max(color,vec3(0.0)),vec3(0.88));
  gl_FragColor=vec4(color,1.0);
}
