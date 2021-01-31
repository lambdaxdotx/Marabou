


import sys
import os
import tensorflow as tf
import numpy as np
import keras2onnx
import onnx
import onnxruntime
from cnn_abs import *
import logging
import time
import argparse

from itertools import product, chain
from maraboupy import MarabouNetworkONNX as monnx
from tensorflow.keras import datasets, layers, models
import matplotlib.pyplot as plt

###########################################################################
####  _____              __ _                   _   _                  ####
#### /  __ \            / _(_)                 | | (_)                 ####
#### | /  \/ ___  _ __ | |_ _  __ _ _   _  __ _| |_ _  ___  _ __  ___  ####
#### | |    / _ \| '_ \|  _| |/ _` | | | |/ _` | __| |/ _ \| '_ \/ __| ####
#### | \__/\ (_) | | | | | | | (_| | |_| | (_| | |_| | (_) | | | \__ \ ####
####  \____/\___/|_| |_|_| |_|\__, |\__,_|\__,_|\__|_|\___/|_| |_|___/ ####
####                           __/ |                                   ####
####                          |___/                                    ####
###########################################################################

tf.compat.v1.enable_v2_behavior()

parser = argparse.ArgumentParser(description='Run MNIST based verification scheme using abstraction')
parser.add_argument("--no_coi",        action="store_true",                        default=False,   help="Don't use COI pruning")
parser.add_argument("--no_verify",     action="store_true",                        default=False,   help="Don't run verification process")
parser.add_argument("--fresh",         action="store_true",                        default=False,   help="Retrain CNN")
parser.add_argument("--cnn_size",      type=str, choices=["big","medium","small"], default="small", help="Which CNN size to use")
parser.add_argument("--run_on",        type=str, choices=["local", "cluster"],     default="local", help="Is the program running on cluster or local run?")
parser.add_argument("--run_suffix",    type=str,                                   default="",      help="Add unique identifier to the run collateral files")
parser.add_argument("--prop_distance", type=int,                                   default=0.1,     help="Distance checked for adversarial robustness (L1 metric)")
args = parser.parse_args()

cfg_freshModelOrig = args.fresh
cfg_noVerify       = args.no_verify
cfg_cnnSizeChoise  = args.cnn_size
cfg_pruneCOI       = not args.no_coi
cfg_propDist       = args.prop_distance
cfg_runOn          = args.run_on
cfg_runSuffix      = args.run_suffix

BIG_MNIST = cfg_cnnSizeChoise == "big"
cexFromImage = False

optionsLocal = Marabou.createOptions(snc=False, verbosity=2)
optionsCluster = Marabou.createOptions(snc=True, verbosity=0, numWorkers=8)
if cfg_runOn == "local":
    mnistProp.optionsObj = optionsLocal
else :
    mnistProp.optionsObj = optionsCluster
    

logging.basicConfig(level = logging.DEBUG, format = "%(asctime)s %(levelname)s %(message)s", filename = "cnnAbsTB.log", filemode = "w")
logger = logging.getLogger('cnnAbsTB')
#logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)
fh = logging.FileHandler('cnnAbsTB.log')
fh.setLevel(logging.DEBUG)
fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(fh)
ch = logging.StreamHandler()
ch.setLevel(logging.ERROR)
ch.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(ch)

logging.getLogger('matplotlib.font_manager').disabled = True

def printLog(s):
    logger.info(s)
    print(s)

###############################################################################
#### ______                                ___  ___          _      _      ####
#### | ___ \                               |  \/  |         | |    | |     ####
#### | |_/ / __ ___ _ __   __ _ _ __ ___   | .  . | ___   __| | ___| |___  ####
#### |  __/ '__/ _ \ '_ \ / _` | '__/ _ \  | |\/| |/ _ \ / _` |/ _ \ / __| ####
#### | |  | | |  __/ |_) | (_| | | |  __/  | |  | | (_) | (_| |  __/ \__ \ ####
#### \_|  |_|  \___| .__/ \__,_|_|  \___|  \_|  |_/\___/ \__,_|\___|_|___/ #### 
####               | |                                                     ####
####               |_|                                                     ####
###############################################################################

## Build initial model.

printLog("Started model building")
modelOrig, replaceLayerName = genCnnForAbsTest(cfg_freshModelOrig=cfg_freshModelOrig,BIG_MNIST=BIG_MNIST)
maskShape = modelOrig.get_layer(name=replaceLayerName).output_shape[:-1]
if maskShape[0] == None:
    maskShape = maskShape[1:]

modelOrigDense = cloneAndMaskConvModel(modelOrig, replaceLayerName, np.ones(maskShape))
#FIXME - created modelOrigDense to compensate on possible translation error when densifing. This way the abstractions are assured to be abstraction of this model.
#compareModels(modelOrig, modelOrigDense)

mnistProp.origMConv = modelOrig
mnistProp.origMDense = modelOrigDense
printLog("Finished model building")


## Choose adversarial example

printLog("Choosing adversarial example")

xAdvInds = range(mnistProp.numTestSamples)
xAdvInd = xAdvInds[0]
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
printLog("Printing original input: {}".format(fName))
plt.title('Example %d. Label: %d' % (xAdvInd, yAdv))
#plt.imshow(xAdv.reshape(xAdv.shape[:-1]), cmap='Greys')
plt.savefig(fName)

maskList = list(genActivationMask(intermidModel(modelOrigDense, "c2"), xAdv, yMax))
printLog("Created {} masks".format(len(maskList)))

#############################################################################################
####  _   _           _  __ _           _   _               ______ _                     ####
#### | | | |         (_)/ _(_)         | | (_)              | ___ \ |                    ####
#### | | | | ___ _ __ _| |_ _  ___ __ _| |_ _  ___  _ __    | |_/ / |__   __ _ ___  ___  ####
#### | | | |/ _ \ '__| |  _| |/ __/ _` | __| |/ _ \| '_ \   |  __/| '_ \ / _` / __|/ _ \ ####
#### \ \_/ /  __/ |  | | | | | (_| (_| | |_| | (_) | | | |  | |   | | | | (_| \__ \  __/ ####
####  \___/ \___|_|  |_|_| |_|\___\__,_|\__|_|\___/|_| |_|  \_|   |_| |_|\__,_|___/\___| ####
####                                                                                     ####
#############################################################################################

if cfg_noVerify:
    printLog("Skipping verification phase")
    exit(0)

printLog("Strating verification phase")

currentMbouRun = 0
isSporious = False
reachedFull = False
successful = None
reachedFinal = False
startTotal = time.time()

for i, mask in enumerate(maskList):
    modelAbs = cloneAndMaskConvModel(modelOrig, replaceLayerName, mask)
    printLog("\n\n\n ----- Start Solving mask number {} ----- \n\n\n {} \n\n\n".format(i+1, mask))
    startLocal = time.time()
    sat, cex, cexPrediction, inputDict, outputDict = runMarabouOnKeras(modelAbs, logger, xAdv, cfg_propDist, yMax, ySecond, "runMarabouOnKeras_mask_{}".format(i+1), coi=cfg_pruneCOI)
    printLog("\n\n\n ----- Finished Solving mask number {}. TimeLocal={}, TimeTotal={} ----- \n\n\n".format(i+1, time.time()-startLocal, time.time()-startTotal))
    currentMbouRun += 1
    isSporious = None
    if sat:
        printLog("Found CEX in mask number {} out of {}, checking if sporious.".format(i+1, len(maskList)))
        isSporious, isSecondGtMax = isCEXSporious(modelOrigDense, xAdv, cfg_propDist, yMax, ySecond, cex, logger)
        printLog("CEX has ySecond {} yMax".format("gt" if isSecondGtMax else "lte"))
        printLog("yMax is{} the maximal value in CEX prediction".format("" if isSporious else " not"))        
        printLog("CEX in mask number {} out of {} is {}sporious.".format(i+1, len(maskList), "" if isSporious else "not "))

        if not isSporious:
            printLog("Found real CEX in mask number {} out of {}".format(i+1, len(maskList)))
            printLog("successful={}/{}".format(i+1, len(maskList)))
            successful = i
            break;
    else:
        printLog("Found UNSAT in mask number {} out of {}".format(i+1, len(maskList)))
        printLog("successful={}/{}".format(i+1, len(maskList)))
        successful = i
        break;
else:
    reachedFinal = True
    printLog("\n\n\n ----- Start Solving Full ----- \n\n\n")
    sat, cex, cexPrediction, inputDict, outputDict = runMarabouOnKeras(modelOrigDense, logger, xAdv, cfg_propDist, yMax, ySecond, "runMarabouOnKeras_Full{}".format(currentMbouRun), coi=cfg_pruneCOI)
    startLocal = time.time()
    printLog("\n\n\n ----- Finished Solving Full. TimeLocal={}, TimeTotal={} ----- \n\n\n".format(time.time()-startLocal, time.time()-startTotal))
    currentMbouRun += 1    

if sat:
    printLog("SAT, reachedFinal={}".format(reachedFinal))
    DOUBLE_CHECK_MARABOU = False
    if DOUBLE_CHECK_MARABOU:
        verificationResult = verifyMarabou(modelOrigDense, cex, cexPrediction, inputDict, outputDict, "verifyMarabou_{}".format(currentMbouRun-1), fromImage=cexFromImage)
        print("verifyMarabou={}".format(verificationResult))
        if not verificationResult[0]:
            raise Exception("Inconsistant Marabou result, verification failed")
    if isCEXSporious(modelOrigDense, xAdv, cfg_propDist, yMax, ySecond, cex, logger)[0]:
        assert reachedFinal
        printLog("Sporious CEX after end")        
        raise Exception("Sporious CEX after end with verified Marabou result")
    if modelOrigDense.predict(np.array([cex])).argmax() != ySecond:
        printLog("Unexepcted prediction result, cex result is {}".format(modelOrigDense.predict(np.array([cex])).argmax()))
    printLog("Found CEX in origin")
    printLog("successful=original")
    printLog("SAT")
else:
    printLog("UNSAT")
    #printLog("verifying UNSAT on unprocessed network")
    #FIXME this is not exactly the same query as the proccessed one.
    #sat, cex, cexPrediction = runMarabouOnKeras(modelOrig, logger, xAdv, cfg_propDist, yMaxUnproc, ySecondUnproc)
    #if not sat:
    #    printLog("Proved UNSAT on unprocessed network")
    #else:
    #    printLog("Found CEX on unprocessed network")


