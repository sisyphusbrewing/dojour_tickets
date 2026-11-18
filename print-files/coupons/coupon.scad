use <Montserrat-ExtraBold.ttf>
F="Montserrat:style=ExtraBold";
W=72; H=24; T=3.6; INLAY=1.0;
PART="all"; LABEL="A";
module art() {
  translate([W/2,16.5]) text("LINDSEY", size=7.4, font=F, halign="center", valign="center");
  translate([W/2,7]) text("“first mate.”", size=4.7, font=F, halign="center", valign="center");
}
module plate2d() offset(2) offset(-2) square([W,H]);
// label engraved on the back (z=0 side faces up when printed face down)
module label() translate([W/2,H/2,-0.01]) linear_extrude(0.61) mirror([1,0]) text(LABEL,size=9,font=F,halign="center",valign="center");
if (PART!="letters") difference(){ linear_extrude(T) plate2d(); label(); translate([0,0,T-INLAY]) linear_extrude(INLAY+1) art(); }
if (PART!="plate") translate([0,0,T-INLAY]) linear_extrude(INLAY) art();
