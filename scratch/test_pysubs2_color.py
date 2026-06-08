# -*- coding: utf-8 -*-
import pysubs2

def test_color():
    subs = pysubs2.SSAFile()
    try:
        style = pysubs2.SSAStyle(
            fontsize=60,
            primarycolor=pysubs2.Color(255, 255, 255),
            backcolor=pysubs2.Color(105, 105, 105, 40),
            outlinecolor=pysubs2.Color(105, 105, 105, 40),
            borderstyle=3,
            outline=10,
            shadow=0,
            alignment=8,
            marginv=1000,
            fontname="Songti SC"
        )
        subs.styles["GlossaryCard"] = style
        print("Successfully initialized style with outlinecolor parameter!")
    except TypeError as e:
        print("Failed to initialize with outlinecolor parameter:", e)
        # Try setting it as attribute
        try:
            style = pysubs2.SSAStyle(
                fontsize=60,
                primarycolor=pysubs2.Color(255, 255, 255),
                backcolor=pysubs2.Color(105, 105, 105, 40),
                borderstyle=3,
                outline=10,
                shadow=0,
                alignment=8,
                marginv=1000,
                fontname="Songti SC"
            )
            style.outlinecolor = pysubs2.Color(105, 105, 105, 40)
            subs.styles["GlossaryCard"] = style
            print("Successfully set outlinecolor as attribute!")
        except Exception as ex:
            print("Failed to set outlinecolor as attribute:", ex)
    
    # Save and read
    subs.save("scratch_test.ass")
    with open("scratch_test.ass", "r", encoding="utf-8") as f:
        print(f.read())

if __name__ == "__main__":
    test_color()
