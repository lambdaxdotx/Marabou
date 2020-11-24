

import sys
import os
import tensorflow as tf
import numpy as np
import keras2onnx
import onnx
import onnxruntime
from cnn_abs import *
import logging

#sys.path.append("/cs/labs/guykatz/matanos/Marabou")
#sys.path.append("/cs/labs/guykatz/matanos/Marabou/maraboupy")

from itertools import product, chain
#from maraboupy import MarabouCore, Marabou
from maraboupy import MarabouNetworkONNX as monnx
from tensorflow.keras import datasets, layers, models
import matplotlib.pyplot as plt

logging.basicConfig(
    level = logging.DEBUG,
    format = "%(asctime)s %(levelname)s %(message)s",
    filename = "cnnAbsTB.log",
    filemode = "w"
)
logger = logging.getLogger('cnnAbsTB')
#logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)
fh = logging.FileHandler('cnnAbsTB.log')
fh.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.ERROR)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)
logger.addHandler(fh)
logger.addHandler(ch)

logger.info("Started model building")
modelOrig, replaceLayerName = genCnnForAbsTest()
maskShape = modelOrig.get_layer(name=replaceLayerName).output_shape[:-1]
if maskShape[0] == None:
    maskShape = maskShape[1:]
#FIXME - created modelOrigDense to compensate on possible translation error when densifing. This way the abstractions are assured to be abstraction of this model.
modelOrigDense = cloneAndMaskConvModel(modelOrig, replaceLayerName, np.ones(maskShape))
print("orig")
[print(l) for l in modelOrig.layers]
print(modelOrig.input)
print("copy")
[print(l) for l in modelOrigDense.layers]
print(modelOrigDense.input)
print("Compare")
compareModels(modelOrig, modelOrigDense)
exit()
logger.info("Finished model building")

logger.info("Choosing adversarial example")
inDist = 0.1
xAdvInd = int(np.random.randint(0, mnistProp.x_test.shape[0], size=1)[0])
xAdv = mnistProp.x_test[xAdvInd]
yAdv = mnistProp.y_test[xAdvInd]
yPredict = modelOrigDense.predict(np.array([xAdv]))
yMax = yPredict.argmax()
yPredictNoMax = np.copy(yPredict)
yPredictNoMax[0][yMax] = 0
ySecond = yPredictNoMax.argmax()
if ySecond == yMax:
    ySecond = 0 if yMax > 0 else 1
    
yPredictUnproc = modelOrig.predict(np.array([xAdv]))
yMaxUnproc = yPredictUnproc.argmax()
yPredictNoMaxUnproc = np.copy(yPredictUnproc)
yPredictNoMaxUnproc[0][yMaxUnproc] = 0
ySecondUnproc = yPredictNoMaxUnproc.argmax()
if ySecondUnproc == yMaxUnproc:
    ySecondUnproc = 0 if yMaxUnproc > 0 else 1
    
fName = "xAdv.png"
logger.info("Printing original input: {}".format(fName))
plt.title('Example %d. Label: %d' % (xAdvInd, yAdv))
plt.imshow(xAdv.reshape(xAdv.shape[:-1]), cmap='Greys')
plt.savefig(fName)
    
logger.info("Starting Abstractions")
maskList = [np.zeros(maskShape)] + [genMask(maskShape, [thresh for dim in maskShape if dim > (2 * thresh)], [dim - thresh for dim in maskShape if dim > (2 * thresh)]) for thresh in reversed(range(int(min(maskShape)/2)))] #FIXME creating too many masks with ones
print("ORIG MASK, len={}".format(len(maskList)))
maskList = [mask for mask in maskList if np.any(np.not_equal(mask, np.ones(mask.shape)))]
logger.info("Created {} masks".format(len(maskList)))
print("UNIQUE MASK, len={}".format(len(maskList)))

isSporious = False
reachedFull = False
successful = None
for i, mask in enumerate(maskList):
    modelAbs = cloneAndMaskConvModel(modelOrig, replaceLayerName, mask)
    sat, cex, cexPrediction = runMarabouOnKeras(modelAbs, logger, xAdv, inDist, yMax, ySecond)
    isSporious = None
    if sat:
        print("Found CEX in mask number {} out of {}, checking if sporious.".format(i, len(maskList)))
        logger.info("Found CEX in mask number {} out of {}, checking if sporious.".format(i, len(maskList)))
        isSporious = isCEXSporious(modelOrigDense, xAdv, inDist, yMax, ySecond, cex, logger)
        print("Found CEX in mask number {} out of {}, checking if sporious.".format(i, len(maskList)))
        logger.info("CEX in mask number {} out of {} is {}sporious.".format(i, len(maskList), "" if isSporious else "not "))        
        if not isSporious:
            print("Found real CEX in mask number {} out of {}".format(i, len(maskList)))
            logger.info("Found real CEX in mask number {} out of {}".format(i, len(maskList)))
            print("successful={}/{}".format(i, len(maskList)))
            successful = i
            break;
    else:
        logger.info("Found UNSAT in mask number {} out of {}".format(i, len(maskList)))
        print("successful={}/{}".format(i, len(maskList)))
        successful = i
        break;
else:
    sat, cex, cexPrediction = runMarabouOnKeras(modelOrigDense, logger, xAdv, inDist, yMax, ySecond)

if sat:
    logger.info("SAT")    
    if isCEXSporious(modelOrigDense, xAdv, inDist, yMax, ySecond, cex, logger):
        logger.info("Sporious CEX after end")
        raise Exception("Sporious CEX after end")
    if modelOrigDense.predict(np.array([cex])).argmax() != ySecond:
        logger.info("Unxepcted prediction result, cex result is {}".format(modelOrigDense.predict(np.array([cex])).argmax()))
    print("Found CEX in origin")
    logger.info("Found CEX in origin")
    print("successful=original")
    print("SAT")
else:
    logger.info("UNSAT")
    print("UNSAT")
    #logger.info("verifying UNSAT on unprocessed network")
    #print("verifying UNSAT on unprocessed network")
    #FIXME this is not exactly the same query as the proccessed one.
    #sat, cex, cexPrediction = runMarabouOnKeras(modelOrig, logger, xAdv, inDist, yMaxUnproc, ySecondUnproc)
    #if not sat:
    #    logger.info("Proved UNSAT on unprocessed network")
    #    print("Proved UNSAT on unprocessed network")
    #else:
    #    logger.info("Found CEX on unprocessed network")
    #    print("Found CEX on unprocessed network")

