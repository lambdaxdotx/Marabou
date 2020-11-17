
import sys
import os
import tensorflow as tf
import numpy as np
import keras2onnx
import onnx
import onnxruntime
from cnn_abs import *

#sys.path.append("/cs/labs/guykatz/matanos/Marabou")
#sys.path.append("/cs/labs/guykatz/matanos/Marabou/maraboupy")

from itertools import product, chain
#from maraboupy import MarabouCore, Marabou
from maraboupy import MarabouNetworkONNX as monnx
from tensorflow.keras import datasets, layers, models
import matplotlib.pyplot as plt

#################################################
#### _____              _____  _   _  _   _  ####
####|  __ \            /  __ \| \ | || \ | | ####
####| |  \/ ___ _ __   | /  \/|  \| ||  \| | ####
####| | __ / _ \ '_ \  | |    | . ` || . ` | ####
####| |_\ \  __/ | | | | \__/\| |\  || |\  | ####
#### \____/\___|_| |_|  \____/\_| \_/\_| \_/ ####
####                                         ####                                   
#################################################


print("Starting model building")
#https://keras.io/examples/vision/mnist_convnet/
    
modelOrig, replaceLayerName = genCnnForAbsTest()
origMOnnx = keras2onnx.convert_keras(modelOrig, modelOrig.name+"_onnx", debug_mode=1)
origMOnnxName = mnistProp.output_model_path(modelOrig)
keras2onnx.save_model(origMOnnx, origMOnnxName)

#################################################################################
#### _____ _                              ______           _                 ####
####/  __ \ |                     ___     | ___ \         | |                ####
####| /  \/ | ___  _ __   ___    ( _ )    | |_/ /___ _ __ | | __ _  ___ ___  ####
####| |   | |/ _ \| '_ \ / _ \   / _ \/\  |    // _ \ '_ \| |/ _` |/ __/ _ \ ####
####| \__/\ | (_) | | | |  __/  | (_>  <  | |\ \  __/ |_) | | (_| | (_|  __/ ####
#### \____/_|\___/|_| |_|\___|   \___/\/  \_| \_\___| .__/|_|\__,_|\___\___| ####
####                                                | |                      ####
####                                                |_|                      ####
#################################################################################

modelAbs = cloneAndMaskConvModel(modelOrig, replaceLayerName, np.ones(modelOrig.get_layer(name=replaceLayerName).output_shape[1:-1]))

absMOnnx = keras2onnx.convert_keras(modelAbs, modelAbs.name+"_onnx", debug_mode=1)
absMOnnxName = mnistProp.output_model_path(modelAbs)
keras2onnx.save_model(absMOnnx, absMOnnxName)

###################################
####  _____       _            ####
#### /  ___|     | |           ####
#### \ `--.  ___ | |_   _____  ####
####  `--. \/ _ \| \ \ / / _ \ ####
#### /\__/ / (_) | |\ V /  __/ ####
#### \____/ \___/|_| \_/ \___| ####
####                           ####
###################################


xAdvInd = int(np.random.randint(0, mnistProp.x_test.shape[0], size=1)[0])
xAdv = mnistProp.x_test[xAdvInd]
yAdv = mnistProp.y_test[xAdvInd]
yPredict = modelOrig.predict(np.array([xAdv]))
yMax = yPredict.argmax()
yPredictNoMax = np.copy(yPredict)
yPredictNoMax[0][yMax] = 0
ySecond = yPredictNoMax.argmax()
inDist = 0.01
if ySecond == yMax:
    ySecond = 0 if yMax > 0 else 1
    
plt.title('Example %d. Label: %d' % (xAdvInd, yAdv))
plt.imshow(xAdv.reshape(xAdv.shape[:-1]), cmap='Greys')
plt.savefig("xAdv.png")

#sess = onnxruntime.InferenceSession(origMOnnxName, onnxruntime.SessionOptions())
#data = [xAdv.astype(np.float32)]
#feed = dict([(input.name, data[n]) for n, input in enumerate(sess.get_inputs())])
#yAdvOnnx = sess.run(None, feed)[0].argmax()
#print("yAdvOnnx={}".format(yAdvOnnx))

##Original
print("\n\n\n\n***************************************************************\n\n\n\n")
print("\n\ncreate origMOnnxMbou:\n")
origMOnnxMbou  = monnx.MarabouNetworkONNX(origMOnnxName)
#print(origMOnnxMbou)
setAdversarial(origMOnnxMbou, xAdv, inDist, yMax, ySecond)
print("\n\n\n\nSolve Orig***************************************************************\n\n\n\n")
vals, stats = origMOnnxMbou.solve()
sat = len(vals) > 0
print("\n\n\n\nFinish solve Orig***************************************************************\n\n\n\n")
if sat:
    cex, cexPrediction = cexToImage(origMOnnxMbou, vals, xAdv)
    plt.title('CEX, MarabouY={}, modelY={}'.format(cexPrediction.argmax(), modelOrig.predict(np.array([cex])).argmax() ))
    plt.imshow(cex.reshape(xAdv.shape[:-1]), cmap='Greys')
    plt.savefig("Cex.png")
    print(cexPrediction)

exit()

##Abstracted
#print("\n\n\n\n***************************************************************\n\n\n\n")
#print("\n\ncreate absMOnnxMbou:\n")
#absMOnnxMbou  = monnx.MarabouNetworkONNX(absMOnnxName)
#print(absMOnnxMbou)
#print("\n\n\n\nSolve Abs***************************************************************\n\n\n\n")
#absMOnnxMbou.solve()
#print("absMOnnxMbou.inputVars={}".format(absMOnnxMbou.inputVars))
#print("absMOnnxMbou.inputVars.shape={}".format(np.array(absMOnnxMbou.inputVars).shape))
#print("absMOnnxMbou.outputVars={}".format(absMOnnxMbou.outputVars))
#print("absMOnnxMbou.numVars={}".format(absMOnnxMbou.numVars))

exit()


















##################################################################
####______     _                    _____ _                   ####
####|  _  \   | |                  /  __ \ |                  ####
####| | | |___| |__  _   _  __ _   | /  \/ | ___  _ __   ___  ####
####| | | / _ \ '_ \| | | |/ _` |  | |   | |/ _ \| '_ \ / _ \ ####
####| |/ /  __/ |_) | |_| | (_| |  | \__/\ | (_) | | | |  __/ ####
####|___/ \___|_.__/ \__,_|\__, |   \____/_|\___/|_| |_|\___| ####
####                        __/ |                             ####
####                       |___/                              ####
##################################################################
##%##
##%##print("\n\n\n Evaluating \n\n\n")
##%##c2 = modelOrig.get_layer(name="c2")
##%##dReplace = modelAbs.get_layer(name="clnDense")
##%##slice_input_shape = modelOrig.get_layer(name="c2").input_shape[1:]
##%##
##%##if mnistProp.cfg_dis_w:
##%##    OrigW = np.ones(c2.get_weights()[0].shape)
##%##else:
##%##    OrigW = c2.get_weights()[0]
##%##AbsW = dReplace.get_weights()[0]
##%##if mnistProp.cfg_dis_b:
##%##    OrigB = np.ones(c2.get_weights()[1].shape)
##%##    AbsB  = np.ones(dReplace.get_weights()[1].shape)
##%##else:
##%##    OrigB = c2.get_weights()[1]
##%##    AbsB  = dReplace.get_weights()[1]
##%##
##%##c2.set_weights([OrigW, OrigB])
##%##dReplace.set_weights([AbsW, AbsB])
##%##
##%##origModelIn = tf.keras.Sequential([ tf.keras.Input(shape=input_shape), modelOrig.get_layer(name="c1"), modelOrig.get_layer(name="mp1") ])
##%##origModelIn.compile(loss=loss, optimizer=optimizer, metrics=metrics)
##%##
##%##origModelSlice = tf.keras.Sequential([ tf.keras.Input(shape=slice_input_shape), c2 ])
##%##origModelSlice.compile(loss=loss, optimizer=optimizer, metrics=metrics)
##%##
##%##modelAbsSlice = tf.keras.Sequential( [tf.keras.Input(shape=slice_input_shape),
##%##                                      modelAbs.get_layer(name="rplcFlat"),
##%##                                      dReplace,
##%##                                      modelAbs.get_layer(name="rplcReshape")])
##%##modelAbsSlice.compile(loss=loss, optimizer=optimizer, metrics=metrics)
##%##
##%##slice_test = [
##%##    np.array([np.zeros(slice_input_shape)]),
##%##    np.array([np.ones(slice_input_shape)]),    
##%##    origModelIn.predict(x_test[:10])
##%##]
##%##
##%##for i,test in enumerate(slice_test):
##%##    evalSlice = np.isclose(modelAbsSlice.predict(test),origModelSlice.predict(test))
##%##    if np.all(evalSlice):
##%##        print("Slice {} Prediction aligned".format(i))
##%##    else:
##%##        print("Slice {} Prediction not aligned".format(i))
##%##        print(np.mean([1 if b else 0 for b in np.nditer(evalSlice)]))
##%##
##%##        '''for origM,absM,e in zip(np.nditer(origModelSlice.predict(test)), np.nditer(modelAbsSlice.predict(test)), np.nditer(evalSlice)):
##%##            if not e:
##%##                if not np.isclose(origM, absM):
##%##                    print("False: \n\torig: {} = {} \n\tabs:  {} = {}".format(origM, np.round(origM, 4),absM,  np.round(absM, 4)))'''
##%##
##%##        print("OrigW, shape={} :: {}".format(OrigW.shape, OrigW))
##%##        print("AbsW, shape={} :: {}".format(AbsW.shape, AbsW))
##%##        print("OrigB, shape={} :: {}".format(OrigB.shape, OrigB))
##%##        print("AbsB, shape={} :: {}".format(AbsB.shape, AbsB))        
##%##        #print("Manual orig:{}".format(manual_result(OrigW, OrigB, test[0])))
##%##        #print("Manual abs:{}".format(manual_result(AbsW, AbsB, test[0])))
##%##
